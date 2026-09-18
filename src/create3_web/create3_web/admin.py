"""Robot administration endpoints, backed by the setup scripts.

Surfaces `scripts/configure_create3.py` and `scripts/preflight_create3.sh` in the
GUI so an operator can see the robot's own configuration, check the clock, run
the diagnostic ladder, and restart the application, ntpd or the robot without
opening a terminal.

The scripts are imported and invoked rather than reimplemented, so there is one
definition of how the robot's web UI is laid out. If the scripts are not mounted
the panel degrades to "unavailable" rather than breaking the rest of the GUI.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import sys
import time

from fastapi import HTTPException

DEFAULT_SCRIPTS_DIR = '/ws/scripts'

_ANSI = re.compile(r'\x1b\[[0-9;]*m')
_RESULT = re.compile(r'^\s*\[(PASS|FAIL|WARN)\]\s+(.*)$')
_SECTION = re.compile(r'^(\d+)\.\s+(.*)$')


def _scripts_dir() -> str:
    d = os.environ.get('CREATE3_SCRIPTS_DIR') or DEFAULT_SCRIPTS_DIR
    if os.path.isdir(d):
        return d
    # Fall back to the checkout layout when running outside the container.
    here = os.path.dirname(os.path.abspath(__file__))
    for up in range(2, 6):
        cand = os.path.join(here, *(['..'] * up), 'scripts')
        cand = os.path.normpath(cand)
        if os.path.isdir(cand):
            return cand
    return d


def _load_configure_module():
    """Import scripts/configure_create3.py by path, or return None."""
    path = os.path.join(_scripts_dir(), 'configure_create3.py')
    if not os.path.isfile(path):
        return None
    if 'configure_create3' in sys.modules:
        return sys.modules['configure_create3']
    spec = importlib.util.spec_from_file_location('configure_create3', path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['configure_create3'] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 - a broken script must not break the GUI
        sys.modules.pop('configure_create3', None)
        return None
    return mod


def register(app, node, robot_ip: str, host_ip: str) -> None:
    """Attach the /api/robot/* routes to an existing FastAPI app."""

    def _robot():
        mod = _load_configure_module()
        if mod is None:
            raise HTTPException(
                status_code=503,
                detail=f'setup scripts not found in {_scripts_dir()}; '
                       'mount ./scripts into the container to enable this panel',
            )
        return mod, mod.Robot(robot_ip, 6)

    @app.get('/api/robot/config')
    async def robot_config() -> dict:
        def work() -> dict:
            mod, robot = _robot()
            cfg = mod.read_config(robot)
            skew = robot.clock_skew()
            peers = re.findall(r'<address>\s*([^<\s]+)\s*</address>', cfg['rmw_override'])
            servers = [
                l.split()[1] for l in cfg['ntp_conf'].splitlines()
                if l.strip().startswith('server') and len(l.split()) > 1
            ]
            safety = re.search(r'safety_override:\s*"?(\w+)"?', cfg['params_yaml'])
            return {
                'ok': True,
                'robot_ip': robot_ip,
                'domain_id': cfg['domain_id'],
                'namespace': cfg['namespace'],
                'rmw': cfg['rmw'],
                'discovery_server': cfg['discovery_enabled'],
                'rmw_override_set': bool(cfg['rmw_override'].strip()),
                'initial_peers': peers,
                'peer_ok': host_ip in peers,
                'ntp_servers': servers,
                'ntp_ok': host_ip in servers,
                'clock_skew': None if skew is None else round(skew, 1),
                'clock_ok': skew is not None and abs(skew) < 5,
                'safety_override': safety.group(1) if safety else None,
            }

        # read_config does blocking HTTP; keep it off the event loop.
        try:
            return await asyncio.to_thread(work)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            return {'ok': False, 'error': str(exc), 'robot_ip': robot_ip}

    async def _post_api(path: str, label: str) -> dict:
        def work() -> dict:
            _, robot = _robot()
            status = robot.post(path)
            return {'ok': True, 'message': f'{label} requested (HTTP {status})'}
        try:
            return await asyncio.to_thread(work)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            return {'ok': False, 'message': str(exc)}

    @app.post('/api/robot/restart-app')
    async def restart_app() -> dict:
        # The robot's nodes vanish for a moment; stop driving into that.
        node.stop()
        return await _post_api('api/restart-app', 'application restart')

    @app.post('/api/robot/restart-ntpd')
    async def restart_ntpd() -> dict:
        return await _post_api('api/restart-ntpd', 'ntpd restart')

    @app.post('/api/robot/reboot')
    async def reboot() -> dict:
        node.stop()
        return await _post_api('api/reboot', 'reboot')

    @app.get('/api/robot/preflight')
    async def preflight(quick: bool = False) -> dict:
        """Run the diagnostic ladder and return it as structured results."""
        script = os.path.join(_scripts_dir(), 'preflight_create3.sh')
        if not os.path.isfile(script):
            raise HTTPException(status_code=503, detail=f'{script} not found')

        cmd = [
            script,
            '--robot', robot_ip,
            '--nuc', host_ip,
            '--namespace', '/' + node.ns,
        ]
        if quick:
            cmd.append('--quick')

        started = time.time()
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            proc.kill()
            return {'ok': False, 'error': 'preflight timed out', 'sections': []}

        sections: list[dict] = []
        for raw in out.decode('utf-8', 'replace').splitlines():
            line = _ANSI.sub('', raw).rstrip()
            if not line.strip():
                continue
            sec = _SECTION.match(line.strip())
            if sec:
                sections.append({'number': int(sec.group(1)), 'title': sec.group(2), 'checks': []})
                continue
            res = _RESULT.match(line)
            if res and sections:
                sections[-1]['checks'].append({'status': res.group(1), 'text': res.group(2).strip()})

        counts = {'PASS': 0, 'FAIL': 0, 'WARN': 0}
        for s in sections:
            for c in s['checks']:
                counts[c['status']] = counts.get(c['status'], 0) + 1

        return {
            'ok': proc.returncode == 0,
            'exit_code': proc.returncode,
            'duration': round(time.time() - started, 1),
            'counts': counts,
            'sections': sections,
        }
