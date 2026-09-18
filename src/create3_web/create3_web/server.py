"""FastAPI layer for the Create 3 web GUI.

Serves the single-page frontend, streams telemetry over a websocket, and exposes
the discrete robot actions over REST.

The websocket carries traffic in both directions so the browser needs only one
connection: the server pushes a telemetry snapshot at a fixed low rate, and the
client pushes velocity commands while a key is held.

Driving a robot from a web page needs a few guarantees that a read-only
dashboard does not, so they are built in rather than bolted on:

* **One driver at a time.** Two browser tabs both sending velocities would fight
  and the robot would judder. Control is a lock that one client holds; everyone
  else is a read-only observer until they explicitly take it.
* **The lock expires.** A holder that closes its laptop never sends a release,
  so the lock is dropped once a holder stops talking.
* **Anyone can stop the robot.** The e-stop deliberately ignores the lock: the
  person who can see the robot is not necessarily the person driving it.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
import uuid

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

# How long a control holder may go silent before the lock is released.
#
# This is deliberately much longer than the velocity deadman in ros_node.py.
# The two timeouts answer different questions: the deadman asks "should the
# robot still be moving?" and must be short, while the lease asks "is this
# operator still here?" and must tolerate someone simply not pressing a key for
# a moment. The client sends a heartbeat so an idle-but-present operator keeps
# the lock; a genuinely disconnected one loses it within the lease.
CONTROL_LEASE_S = 10.0


class ControlLock:
    """Single-writer lock over the robot's velocity input."""

    def __init__(self, lease_s: float = CONTROL_LEASE_S):
        self._holder: str | None = None
        self._label: str = ''
        self._last_seen: float = 0.0
        self._lease_s = lease_s

    def _expire(self) -> None:
        if self._holder and (time.time() - self._last_seen) > self._lease_s:
            self._holder = None
            self._label = ''

    def acquire(self, client_id: str, label: str = '') -> bool:
        self._expire()
        if self._holder in (None, client_id):
            self._holder = client_id
            self._label = label or self._label
            self._last_seen = time.time()
            return True
        return False

    def release(self, client_id: str) -> None:
        if self._holder == client_id:
            self._holder = None
            self._label = ''

    def touch(self, client_id: str) -> bool:
        """Refresh the lease. Returns whether this client currently holds it."""
        self._expire()
        if self._holder == client_id:
            self._last_seen = time.time()
            return True
        return False

    def status(self) -> dict:
        self._expire()
        return {
            'holder': self._holder,
            'label': self._label,
            'held': self._holder is not None,
        }


def create_app(
    node,
    web_dir: str,
    telemetry_hz: float = 10.0,
    token: str | None = None,
    robot_ip: str = '192.168.186.2',
    host_ip: str = '192.168.186.3',
) -> FastAPI:
    app = FastAPI(title='CPSL Create 3', docs_url=None, redoc_url=None)
    lock = ControlLock()

    def check_token(request: Request) -> None:
        if not token:
            return
        supplied = request.query_params.get('token') or request.headers.get('x-auth-token')
        # Constant-time compare so the token cannot be recovered by timing.
        if not supplied or not secrets.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail='invalid or missing token')

    # Robot administration, backed by scripts/. Degrades to 503 if the scripts
    # are not mounted, which must not stop the rest of the GUI from loading.
    try:
        from .admin import register as register_admin
        register_admin(app, node, robot_ip, host_ip)
    except Exception:  # noqa: BLE001
        pass

    # --- static frontend -------------------------------------------------
    @app.get('/')
    async def index() -> FileResponse:
        return FileResponse(os.path.join(web_dir, 'index.html'))

    # colcon --symlink-install populates the package's share directory with
    # symlinks into the build tree. Starlette's StaticFiles refuses to serve a
    # symlink whose target resolves outside the mounted directory, so assets
    # would 404 in exactly the layout the container ships. Serving them
    # explicitly keeps behaviour identical across colcon and starlette versions.
    _web_root = os.path.abspath(web_dir)

    @app.get('/static/{path:path}')
    async def static_asset(path: str) -> FileResponse:
        # Resolve against the request path, before following any symlink, so
        # traversal is rejected regardless of where the link points.
        target = os.path.abspath(os.path.join(_web_root, path))
        if target != _web_root and not target.startswith(_web_root + os.sep):
            raise HTTPException(status_code=404, detail='not found')
        if not os.path.isfile(target):
            raise HTTPException(status_code=404, detail='not found')
        return FileResponse(target)

    # --- REST ------------------------------------------------------------
    @app.get('/api/state')
    async def api_state(request: Request) -> JSONResponse:
        check_token(request)
        snap = node.snapshot()
        snap['control'] = lock.status()
        return JSONResponse(snap)

    @app.post('/api/dock')
    async def api_dock(request: Request) -> JSONResponse:
        check_token(request)
        ok, msg = node.start_action('dock')
        return JSONResponse({'ok': ok, 'message': msg}, status_code=200 if ok else 409)

    @app.post('/api/undock')
    async def api_undock(request: Request) -> JSONResponse:
        check_token(request)
        ok, msg = node.start_action('undock')
        return JSONResponse({'ok': ok, 'message': msg}, status_code=200 if ok else 409)

    @app.post('/api/cancel')
    async def api_cancel(request: Request) -> JSONResponse:
        check_token(request)
        return JSONResponse({'ok': node.cancel_action()})

    @app.post('/api/estop')
    async def api_estop(request: Request) -> JSONResponse:
        # Deliberately not gated on holding the control lock. Whoever can see
        # the robot should be able to stop it.
        check_token(request)
        body = {}
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - an empty body means "engage"
            pass
        engaged = bool(body.get('engaged', True))
        node.set_estop(engaged)
        if engaged:
            lock.release(lock.status().get('holder') or '')
        return JSONResponse({'ok': True, 'estop': node.estop})

    # --- websocket -------------------------------------------------------
    @app.websocket('/ws')
    async def ws(websocket: WebSocket) -> None:
        if token:
            supplied = websocket.query_params.get('token')
            if not supplied or not secrets.compare_digest(supplied, token):
                await websocket.close(code=4401)
                return

        await websocket.accept()
        client_id = uuid.uuid4().hex[:12]
        await websocket.send_text(json.dumps({
            'type': 'hello',
            'client_id': client_id,
            'namespace': node.ns,
            'limits': {'max_linear': node.max_linear, 'max_angular': node.max_angular},
        }))

        async def pump_telemetry() -> None:
            period = 1.0 / telemetry_hz
            while True:
                snap = node.snapshot()
                snap['type'] = 'telemetry'
                snap['control'] = lock.status()
                snap['you'] = client_id
                await websocket.send_text(json.dumps(snap))
                await asyncio.sleep(period)

        pump = asyncio.create_task(pump_telemetry())
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                # Any message from the holder proves they are still there and
                # refreshes the lease, so control does not evaporate between
                # key presses.
                lock.touch(client_id)

                kind = msg.get('type')
                if kind == 'twist':
                    # Silently ignored for non-holders; the UI already shows who
                    # holds control, so this is not an error worth reporting.
                    if lock.touch(client_id):
                        node.set_twist(msg.get('linear', 0.0), msg.get('angular', 0.0))
                elif kind == 'acquire':
                    granted = lock.acquire(client_id, msg.get('label', ''))
                    await websocket.send_text(json.dumps({
                        'type': 'control', 'granted': granted, **lock.status(),
                    }))
                elif kind == 'release':
                    lock.release(client_id)
                    node.stop()
                elif kind == 'stop':
                    if lock.touch(client_id):
                        node.stop()
                elif kind == 'ping':
                    await websocket.send_text(json.dumps({'type': 'pong', 't': time.time()}))
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001 - never let one client kill the server
            pass
        finally:
            pump.cancel()
            # A closed tab must not leave the robot driving or the lock held.
            if lock.status().get('holder') == client_id:
                lock.release(client_id)
                node.stop()

    return app
