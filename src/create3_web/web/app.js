/* CPSL Create 3 web GUI.
 *
 * One websocket carries telemetry down and velocity commands up. The server
 * enforces the deadman and the single-driver lock; this file is responsible for
 * never lying to the operator about which of those is currently true.
 */
'use strict';

const TOKEN = new URLSearchParams(location.search).get('token') || '';
const CMD_HZ = 20;            // how often we repeat the held command
const TRAIL_MAX = 1200;       // odometry points retained for the plot

const $ = (id) => document.getElementById(id);
const fmt = (v, n = 2) => (v === undefined || v === null || Number.isNaN(v)) ? '--' : Number(v).toFixed(n);

let ws = null;
let clientId = null;
let hasControl = false;
let estopEngaged = false;
let limits = { max_linear: 0.31, max_angular: 1.90 };
const trail = [];

/* ---------------------------------------------------------------- socket */
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const qs = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : '';
  ws = new WebSocket(`${proto}://${location.host}/ws${qs}`);

  ws.onopen = () => setConn(true, 'connected');
  ws.onclose = () => {
    setConn(false, 'disconnected — retrying');
    // Losing the socket means losing control; say so immediately rather than
    // leaving a stale "you are driving" badge on screen.
    hasControl = false;
    renderControl({ held: false });
    keys.clear();
    paintKeys();
    setTimeout(connect, 1500);
  };
  ws.onerror = () => setConn(false, 'connection error');
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === 'hello') {
      clientId = msg.client_id;
      limits = msg.limits || limits;
      $('ns').textContent = msg.namespace || 'create 3';
      document.title = `${msg.namespace || 'create 3'} · CPSL`;
      applyLimits();
    } else if (msg.type === 'telemetry') {
      render(msg);
    } else if (msg.type === 'control') {
      hasControl = !!msg.granted;
      renderControl(msg);
    }
  };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function setConn(ok, text) {
  $('conn-dot').className = 'dot ' + (ok ? 'on' : 'off');
  $('conn-text').textContent = text;
}

/* --------------------------------------------------------------- render */
function staleClass(el, age, limit = 3) {
  el.classList.toggle('stale', !(age !== undefined && age !== null && age < limit));
}

function render(s) {
  const ages = s.ages || {};

  // Battery
  const b = s.battery;
  if (b) {
    const pct = Math.round((b.percentage || 0) * 100);
    $('bat-pct').textContent = pct;
    $('bat-bar').style.width = pct + '%';
    $('bat-bar').style.background = pct > 40 ? 'var(--ok)' : pct > 15 ? 'var(--warn)' : 'var(--bad)';
    $('bat-v').textContent = fmt(b.voltage, 2) + ' V';
    $('bat-state').textContent = b.present ? (s.dock && s.dock.is_docked ? 'charging' : 'discharging') : 'absent';
  }
  staleClass($('tile-battery'), ages.battery, 30);

  // Dock
  if (s.dock) {
    $('dock-state').textContent = s.dock.is_docked ? 'Docked' : 'Undocked';
    $('dock-visible').textContent = s.dock.dock_visible ? 'dock visible' : 'dock not visible';
    $('btn-dock').disabled = s.dock.is_docked || estopEngaged;
    $('btn-undock').disabled = !s.dock.is_docked || estopEngaged;
  }
  staleClass($('tile-dock'), ages.dock, 30);

  const a = s.action || {};
  $('action-state').textContent =
    (a.name && a.state && a.state !== 'idle') ? `${a.name}: ${a.state}${a.detail ? ' (' + a.detail + ')' : ''}` : '';

  // Motion
  if (s.odom) {
    $('od-x').textContent = fmt(s.odom.x, 3) + ' m';
    $('od-y').textContent = fmt(s.odom.y, 3) + ' m';
    $('od-yaw').textContent = fmt(s.odom.yaw * 180 / Math.PI, 1) + '°';
    $('od-vx').textContent = fmt(s.odom.vx, 3) + ' m/s';
    $('od-wz').textContent = fmt(s.odom.wz, 3) + ' rad/s';
    pushTrail(s.odom.x, s.odom.y, s.odom.yaw);
  }
  staleClass($('tile-motion'), ages.odom);

  // Safety
  const hz = s.hazards || [];
  const flags = [];
  if (s.kidnapped) flags.push('kidnapped');
  if (s.stopped) flags.push('stopped');
  const safetyEl = $('safety-state');
  if (estopEngaged) { safetyEl.textContent = 'E-STOP'; safetyEl.style.color = 'var(--bad)'; }
  else if (hz.length) { safetyEl.textContent = 'Hazard'; safetyEl.style.color = 'var(--bad)'; }
  else if (flags.length) { safetyEl.textContent = flags.join(', '); safetyEl.style.color = 'var(--warn)'; }
  else { safetyEl.textContent = 'Clear'; safetyEl.style.color = 'var(--ok)'; }

  const chips = $('hazard-chips');
  chips.textContent = '';
  hz.forEach((h) => {
    const d = document.createElement('span');
    d.className = 'chip';
    d.textContent = h;
    chips.appendChild(d);
  });

  $('wheel-state').textContent = s.wheels
    ? `wheels ${fmt(s.wheels.left, 2)} / ${fmt(s.wheels.right, 2)} rad/s` : '--';
  // Gated on stop_status rather than hazard_detection: the latter only publishes
  // when a hazard exists, so an absence of messages is the healthy case and must
  // not grey the tile out. stop_status comes from the same node and is continuous.
  staleClass($('tile-safety'), ages.stopped, 30);

  // E-stop + control
  estopEngaged = !!s.estop;
  $('estop').classList.toggle('engaged', estopEngaged);
  $('estop').textContent = estopEngaged ? 'E-STOP ON — CLEAR' : 'E-STOP';

  if (s.control) {
    hasControl = s.control.holder && s.control.holder === s.you;
    renderControl(s.control);
  }
  if (s.cmd) $('cmd-echo').textContent = `cmd ${fmt(s.cmd.linear)} / ${fmt(s.cmd.angular)}`;

  $('foot').textContent = `${s.online ? 'robot online' : 'robot offline'} · updated ${new Date(s.t * 1000).toLocaleTimeString()}`;
}

function renderControl(c) {
  const el = $('control-state');
  const btn = $('btn-control');
  if (hasControl) {
    el.textContent = 'you are driving';
    el.classList.add('has');
    btn.textContent = 'Release control';
    btn.classList.add('active');
  } else {
    el.textContent = c && c.held ? 'another client is driving' : 'read-only';
    el.classList.remove('has');
    btn.textContent = 'Take control';
    btn.classList.remove('active');
  }
}

/* ---------------------------------------------------------------- trail */
function pushTrail(x, y) {
  const last = trail[trail.length - 1];
  if (last && Math.hypot(x - last[0], y - last[1]) < 0.01) return;
  trail.push([x, y]);
  if (trail.length > TRAIL_MAX) trail.shift();
  drawTrail();
}

function drawTrail() {
  const cv = $('trail');
  const ctx = cv.getContext('2d');
  const W = cv.width, H = cv.height;
  ctx.clearRect(0, 0, W, H);

  const css = getComputedStyle(document.documentElement);
  const line = css.getPropertyValue('--line').trim() || '#ddd';
  const accent = css.getPropertyValue('--accent').trim() || '#2563eb';
  const muted = css.getPropertyValue('--muted').trim() || '#888';

  if (!trail.length) { $('trail-scale').textContent = 'no odometry yet'; return; }

  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const [x, y] of trail) {
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  // Keep at least a 1 m window so a stationary robot does not get an absurd zoom.
  const pad = 0.5;
  const spanX = Math.max(maxX - minX, 1) + pad * 2;
  const spanY = Math.max(maxY - minY, 1) + pad * 2;
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const scale = Math.min(W / spanX, H / spanY);

  // ROS x is forward and y is left, so screen x = -y and screen y = -x.
  const toPx = (x, y) => [W / 2 - (y - cy) * scale, H / 2 - (x - cx) * scale];

  ctx.strokeStyle = line; ctx.lineWidth = 1;
  for (let g = Math.ceil(cy - spanY / 2); g <= cy + spanY / 2; g++) {
    const [, py] = toPx(g, 0); const [px] = toPx(0, g);
    ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, H); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(W, py); ctx.stroke();
  }

  ctx.strokeStyle = accent; ctx.lineWidth = 2; ctx.lineJoin = 'round';
  ctx.beginPath();
  trail.forEach(([x, y], i) => { const [px, py] = toPx(x, y); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
  ctx.stroke();

  const [hx, hy] = toPx(trail[trail.length - 1][0], trail[trail.length - 1][1]);
  ctx.fillStyle = accent;
  ctx.beginPath(); ctx.arc(hx, hy, 5, 0, Math.PI * 2); ctx.fill();

  ctx.fillStyle = muted; ctx.font = '11px ui-monospace, monospace';
  $('trail-scale').textContent =
    `${trail.length} pts · ${(spanX).toFixed(1)} × ${(spanY).toFixed(1)} m · 1 m grid`;
}

/* ------------------------------------------------------------- controls */
const keys = new Set();
const KEYMAP = {
  w: 'w', arrowup: 'w', s: 's', arrowdown: 's',
  a: 'a', arrowleft: 'a', d: 'd', arrowright: 'd', ' ': ' ',
};

function currentTwist() {
  const lin = Number($('sl-lin').value);
  const ang = Number($('sl-ang').value);
  let l = 0, a = 0;
  if (keys.has('w')) l += lin;
  if (keys.has('s')) l -= lin;
  if (keys.has('a')) a += ang;
  if (keys.has('d')) a -= ang;
  return [l, a];
}

function paintKeys() {
  document.querySelectorAll('.key').forEach((el) => {
    el.classList.toggle('on', keys.has(el.dataset.k));
  });
}

function pressKey(k) {
  if (k === ' ') { keys.clear(); paintKeys(); send({ type: 'stop' }); return; }
  keys.add(k); paintKeys();
}
function releaseKey(k) { keys.delete(k); paintKeys(); }

window.addEventListener('keydown', (e) => {
  if (e.target.matches('input, textarea, button')) return;
  const k = KEYMAP[e.key.toLowerCase()];
  if (!k) return;
  e.preventDefault();
  if (!hasControl) return;
  pressKey(k);
});
window.addEventListener('keyup', (e) => {
  const k = KEYMAP[e.key.toLowerCase()];
  if (k) { e.preventDefault(); releaseKey(k); }
});

// Browsers drop key-up events when the window loses focus, which would
// otherwise leave a key latched and the robot driving. The server's deadman
// catches this too; clearing here keeps the UI honest as well.
window.addEventListener('blur', () => { keys.clear(); paintKeys(); });
document.addEventListener('visibilitychange', () => {
  if (document.hidden) { keys.clear(); paintKeys(); }
});

document.querySelectorAll('.key').forEach((el) => {
  const k = el.dataset.k;
  const down = (e) => { e.preventDefault(); if (hasControl) pressKey(k); };
  const up = (e) => { e.preventDefault(); releaseKey(k); };
  el.addEventListener('pointerdown', down);
  el.addEventListener('pointerup', up);
  el.addEventListener('pointerleave', up);
  el.addEventListener('pointercancel', up);
});

// Repeat the held command. The server treats silence as "stop", so this must
// keep talking for as long as a key is actually down.
setInterval(() => {
  if (!hasControl) return;
  const [l, a] = currentTwist();
  if (l !== 0 || a !== 0 || keys.size) send({ type: 'twist', linear: l, angular: a });
}, 1000 / CMD_HZ);

// Keep the control lease alive while we hold it. Without this, letting go of
// the keys for longer than the lease would silently hand control back.
setInterval(() => { if (hasControl) send({ type: 'ping' }); }, 2000);

function applyLimits() {
  $('sl-lin').max = limits.max_linear;
  $('sl-ang').max = limits.max_angular;
  if (Number($('sl-lin').value) > limits.max_linear) $('sl-lin').value = limits.max_linear;
  if (Number($('sl-ang').value) > limits.max_angular) $('sl-ang').value = limits.max_angular;
  $('out-lin').textContent = Number($('sl-lin').value).toFixed(2);
  $('out-ang').textContent = Number($('sl-ang').value).toFixed(2);
}

$('sl-lin').addEventListener('input', (e) => { $('out-lin').textContent = Number(e.target.value).toFixed(2); });
$('sl-ang').addEventListener('input', (e) => { $('out-ang').textContent = Number(e.target.value).toFixed(2); });

$('btn-control').addEventListener('click', () => {
  if (hasControl) { send({ type: 'release' }); hasControl = false; renderControl({ held: false }); }
  else { send({ type: 'acquire', label: navigator.platform || 'browser' }); }
});

$('btn-trail').addEventListener('click', () => { trail.length = 0; drawTrail(); });

async function post(path, body) {
  const qs = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : '';
  try {
    const r = await fetch(path + qs, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    return await r.json();
  } catch (err) {
    return { ok: false, message: String(err) };
  }
}

$('btn-dock').addEventListener('click', () => post('/api/dock'));
$('btn-undock').addEventListener('click', () => post('/api/undock'));
$('estop').addEventListener('click', () => {
  keys.clear(); paintKeys();
  post('/api/estop', { engaged: !estopEngaged });
});

connect();
drawTrail();

/* ------------------------------------------------- robot setup panel */
async function getJSON(path) {
  const qs = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : '';
  const sep = path.includes('?') ? '&' : '';
  try {
    const r = await fetch(path + (TOKEN ? sep + qs.slice(1) : ''));
    return await r.json();
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

function kv(label, value, state) {
  const d = document.createElement('div');
  d.className = 'kv';
  const s = document.createElement('span');
  s.textContent = label;
  const b = document.createElement('b');
  b.textContent = value;
  if (state === true) b.classList.add('good');
  if (state === false) b.classList.add('bad');
  d.append(s, b);
  return d;
}

async function refreshConfig() {
  const grid = $('cfg-grid');
  grid.textContent = '';
  const c = await getJSON('/api/robot/config');
  if (!c || c.ok === false) {
    const msg = document.createElement('span');
    msg.className = 'sub';
    msg.textContent = c && (c.detail || c.error) ? (c.detail || c.error) : 'unavailable';
    grid.appendChild(msg);
    return;
  }
  grid.append(
    kv('robot', c.robot_ip),
    kv('namespace', c.namespace || '--'),
    kv('domain id', c.domain_id ?? '--'),
    kv('RMW', c.rmw || '--', c.rmw === 'rmw_fastrtps_cpp'),
    kv('discovery server', c.discovery_server ? 'ENABLED' : 'disabled', !c.discovery_server),
    kv('initial peers', (c.initial_peers || []).join(', ') || 'none', c.peer_ok),
    kv('ntp servers', (c.ntp_servers || []).join(', ') || 'none', c.ntp_ok),
    kv('clock skew', c.clock_skew === null ? 'unknown' : c.clock_skew + ' s', c.clock_ok),
    kv('safety override', c.safety_override || '--'),
  );
}

async function runPreflight() {
  const out = $('preflight-out');
  const btn = $('btn-preflight');
  out.textContent = '';
  btn.disabled = true;
  btn.textContent = 'Running…';

  const r = await getJSON('/api/robot/preflight');

  btn.disabled = false;
  btn.textContent = 'Run preflight';

  if (!r || !r.sections) {
    $('admin-msg').textContent = (r && (r.detail || r.error)) || 'preflight unavailable';
    return;
  }
  const c = r.counts || {};
  $('admin-msg').textContent =
    `${c.PASS || 0} passed, ${c.WARN || 0} warning(s), ${c.FAIL || 0} failed — ${r.duration}s`;

  r.sections.forEach((sec) => {
    const box = document.createElement('div');
    box.className = 'pf-sec';
    const h = document.createElement('h3');
    h.textContent = `${sec.number}. ${sec.title}`;
    box.appendChild(h);
    sec.checks.forEach((chk) => {
      const row = document.createElement('div');
      row.className = 'pf-row';
      const tag = document.createElement('span');
      tag.className = 'pf-tag pf-' + chk.status;
      tag.textContent = chk.status;
      const txt = document.createElement('span');
      txt.textContent = chk.text;
      row.append(tag, txt);
      box.appendChild(row);
    });
    out.appendChild(box);
  });
}

async function adminPost(path, label, confirmText) {
  if (confirmText && !window.confirm(confirmText)) return;
  $('admin-msg').textContent = label + '…';
  const r = await post(path);
  $('admin-msg').textContent = (r && r.message) || (r && r.detail) || 'done';
}

$('btn-refresh-cfg').addEventListener('click', refreshConfig);
$('btn-preflight').addEventListener('click', runPreflight);
$('btn-restart-ntpd').addEventListener('click',
  () => adminPost('/api/robot/restart-ntpd', 'Restarting ntpd'));
$('btn-restart-app').addEventListener('click',
  () => adminPost('/api/robot/restart-app', 'Restarting application',
    'Restart the robot application? Its ROS nodes will disappear for about a minute.'));
$('btn-reboot').addEventListener('click',
  () => adminPost('/api/robot/reboot', 'Rebooting',
    'Reboot the robot? This takes several minutes and it will chime when ready.'));

refreshConfig();
