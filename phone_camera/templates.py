"""Inline HTML templates for the phone-pairing flow.

Kept as Python strings (no Jinja) so the package has zero filesystem
dependencies and the templates can be substituted with `str.format` safely
— every untrusted value is escaped first.
"""

from __future__ import annotations

import html


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


def render_pair_page(*, token: str, cam_url: str, qr_url: str, status_url: str) -> str:
    """Desktop pair page: shows QR pointing at the phone capture URL."""
    cam_url_safe = _esc(cam_url)
    qr_url_safe = _esc(qr_url)
    status_url_safe = _esc(status_url)
    token_safe = _esc(token)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SafeWatch · Pair phone camera</title>
<style>
:root {{
  color-scheme: dark;
  --bg: #0b0d12;
  --fg: #f5f7fa;
  --muted: #8b94a7;
  --accent: #5cf2c4;
  --accent-dim: #2a8a6e;
  --warn: #f0b35b;
  --card: #161a23;
  --border: #232838;
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; min-height: 100%; background: var(--bg); color: var(--fg); font: 16px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro", system-ui, sans-serif; }}
.wrap {{ max-width: 980px; margin: 0 auto; padding: 48px 24px 64px; }}
header {{ display: flex; align-items: center; gap: 14px; margin-bottom: 8px; }}
.logo {{ width: 36px; height: 36px; border-radius: 9px; background: linear-gradient(135deg, var(--accent) 0%, #2c8aff 100%); display: grid; place-items: center; font-weight: 700; color: #0b0d12; }}
h1 {{ font-size: 28px; margin: 0; letter-spacing: -0.01em; }}
.subtitle {{ color: var(--muted); margin: 6px 0 36px; font-size: 16px; }}
.grid {{ display: grid; grid-template-columns: 1.1fr 1fr; gap: 28px; align-items: stretch; }}
@media (max-width: 760px) {{ .grid {{ grid-template-columns: 1fr; }} }}
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: 18px; padding: 24px; }}
.qr-card {{ display: flex; flex-direction: column; align-items: center; }}
.qr-frame {{ background: #fff; padding: 14px; border-radius: 14px; box-shadow: 0 8px 30px rgba(0,0,0,0.4); }}
.qr-frame img {{ display: block; width: 280px; height: 280px; image-rendering: pixelated; }}
.qr-help {{ color: var(--muted); margin-top: 16px; text-align: center; font-size: 14px; }}
.url-row {{ margin-top: 14px; display: flex; gap: 8px; align-items: stretch; width: 100%; }}
.url-input {{ flex: 1; min-width: 0; background: #0b0d12; border: 1px solid var(--border); color: var(--fg); border-radius: 10px; padding: 10px 12px; font: 13px/1.4 ui-monospace, monospace; }}
button {{ background: var(--accent); color: #0b0d12; border: 0; border-radius: 10px; padding: 10px 14px; font-weight: 600; cursor: pointer; font-size: 14px; }}
button.ghost {{ background: transparent; color: var(--fg); border: 1px solid var(--border); }}
button:hover {{ filter: brightness(1.05); }}
.preview {{ position: relative; aspect-ratio: 4/3; background: #000; border-radius: 14px; overflow: hidden; border: 1px solid var(--border); }}
.preview img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
.preview .placeholder {{ position: absolute; inset: 0; display: grid; place-items: center; color: var(--muted); text-align: center; padding: 24px; font-size: 15px; }}
.status {{ display: flex; align-items: center; gap: 10px; margin-top: 18px; }}
.dot {{ width: 12px; height: 12px; border-radius: 50%; background: var(--muted); box-shadow: 0 0 0 0 rgba(0,0,0,0); transition: background .2s, box-shadow .2s; }}
.dot.live {{ background: var(--accent); box-shadow: 0 0 0 4px rgba(92,242,196,0.18); animation: pulse 1.6s ease-in-out infinite; }}
.dot.warn {{ background: var(--warn); }}
@keyframes pulse {{ 0% {{ box-shadow: 0 0 0 0 rgba(92,242,196,0.45); }} 70% {{ box-shadow: 0 0 0 8px rgba(92,242,196,0); }} 100% {{ box-shadow: 0 0 0 0 rgba(92,242,196,0); }} }}
.status-text {{ flex: 1; }}
.status-text strong {{ display: block; font-size: 15px; }}
.status-text span {{ color: var(--muted); font-size: 13px; }}
.steps {{ list-style: none; padding: 0; margin: 0 0 24px; counter-reset: step; }}
.steps li {{ display: flex; gap: 14px; align-items: flex-start; margin-bottom: 14px; }}
.steps li::before {{ counter-increment: step; content: counter(step); width: 28px; height: 28px; flex: 0 0 28px; border-radius: 50%; background: var(--border); color: var(--accent); display: grid; place-items: center; font-weight: 700; font-size: 13px; }}
footer {{ color: var(--muted); font-size: 12px; margin-top: 48px; text-align: center; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">3E</div>
    <div>
      <h1>Pair a phone as a Third Eye</h1>
      <div class="subtitle">Any device, any camera — turned into a SafeWatch sensor in one scan.</div>
    </div>
  </header>

  <div class="grid">
    <section class="card">
      <ol class="steps">
        <li>Open your phone&rsquo;s camera and point it at the QR code.</li>
        <li>Tap the link that appears, then allow camera access.</li>
        <li>Lay the phone where you want SafeWatch to watch — that&rsquo;s it.</li>
      </ol>
      <div class="status" id="statusRow">
        <div class="dot warn" id="statusDot"></div>
        <div class="status-text">
          <strong id="statusTitle">Waiting for phone&hellip;</strong>
          <span id="statusSub">Scan the QR with the phone you want to use.</span>
        </div>
      </div>
      <div class="preview" style="margin-top:18px;">
        <img id="previewImg" alt="Live phone preview" style="display:none;">
        <div class="placeholder" id="previewPlaceholder">Live preview will appear here once the phone connects.</div>
      </div>
    </section>

    <section class="card qr-card">
      <div class="qr-frame">
        <img src="{qr_url_safe}" alt="QR code" id="qrImg">
      </div>
      <div class="qr-help">Pairing token <code style="color:var(--accent);">{token_safe}</code></div>
      <div class="url-row">
        <input class="url-input" id="urlInput" value="{cam_url_safe}" readonly aria-label="Phone camera URL">
        <button id="copyBtn">Copy</button>
      </div>
      <div class="qr-help" style="margin-top:18px;">If the QR can&rsquo;t reach your phone, paste this URL into your phone&rsquo;s browser instead.</div>
    </section>
  </div>

  <footer>SafeWatch · phone-camera pairing · token <code>{token_safe}</code></footer>
</div>

<script>
const STATUS_URL = "{status_url_safe}";
const TOKEN = "{token_safe}";
const PREVIEW_URL = "/camera/" + TOKEN + "/latest.jpg";
const dot = document.getElementById("statusDot");
const title = document.getElementById("statusTitle");
const sub = document.getElementById("statusSub");
const previewImg = document.getElementById("previewImg");
const previewPh = document.getElementById("previewPlaceholder");

document.getElementById("copyBtn").onclick = () => {{
  const i = document.getElementById("urlInput");
  i.select(); i.setSelectionRange(0, 99999);
  try {{ navigator.clipboard.writeText(i.value); }} catch (e) {{ document.execCommand("copy"); }}
  document.getElementById("copyBtn").textContent = "Copied";
  setTimeout(() => document.getElementById("copyBtn").textContent = "Copy", 1500);
}};

let lastFrameAt = 0;
async function tick() {{
  try {{
    const r = await fetch(STATUS_URL, {{ cache: "no-store" }});
    const s = await r.json();
    if (s.live) {{
      dot.className = "dot live";
      title.textContent = (s.label || "Phone") + " connected · streaming live";
      sub.textContent = (s.frame_count || 0) + " frames · " + (s.width || "?") + "x" + (s.height || "?");
      if (s.last_frame_at && s.last_frame_at !== lastFrameAt) {{
        lastFrameAt = s.last_frame_at;
        previewImg.src = PREVIEW_URL + "?t=" + Date.now();
        previewImg.style.display = "block";
        previewPh.style.display = "none";
      }}
    }} else if (s.connected) {{
      dot.className = "dot warn";
      title.textContent = "Phone disconnected";
      sub.textContent = "Last frame " + (s.age_seconds ? s.age_seconds.toFixed(1) + "s ago" : "a moment ago");
    }} else {{
      dot.className = "dot warn";
      title.textContent = "Waiting for phone\u2026";
      sub.textContent = "Scan the QR with the phone you want to use.";
    }}
  }} catch (e) {{
    dot.className = "dot";
    title.textContent = "Pair page lost the server";
    sub.textContent = String(e);
  }}
}}
tick();
setInterval(tick, 800);
</script>
</body>
</html>"""


def render_camera_page(*, token: str, ws_url: str, label_default: str) -> str:
    """Phone capture page: getUserMedia + WebSocket frame upload."""
    token_safe = _esc(token)
    ws_url_safe = _esc(ws_url)
    label_safe = _esc(label_default)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>SafeWatch Third Eye</title>
<style>
* {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
html, body {{ margin: 0; padding: 0; height: 100vh; background: #000; color: #fff; font: 15px/1.4 -apple-system, BlinkMacSystemFont, "SF Pro", system-ui, sans-serif; overscroll-behavior: none; }}
.shell {{ position: fixed; inset: 0; display: flex; flex-direction: column; }}
video {{ flex: 1 1 auto; min-height: 0; width: 100%; object-fit: cover; background: #000; }}
.controls {{ padding: 18px max(16px, env(safe-area-inset-right)) max(18px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left)); background: linear-gradient(0deg, rgba(0,0,0,0.92), rgba(0,0,0,0)); display: grid; gap: 10px; }}
.row {{ display: flex; align-items: center; gap: 12px; }}
.dot {{ width: 12px; height: 12px; border-radius: 50%; background: #f0b35b; transition: background .2s; }}
.dot.live {{ background: #5cf2c4; box-shadow: 0 0 0 4px rgba(92,242,196,.18); animation: pulse 1.6s ease-in-out infinite; }}
@keyframes pulse {{ 0% {{ box-shadow: 0 0 0 0 rgba(92,242,196,.45); }} 70% {{ box-shadow: 0 0 0 8px rgba(92,242,196,0); }} 100% {{ box-shadow: 0 0 0 0 rgba(92,242,196,0); }} }}
button {{ background: #5cf2c4; color: #0b0d12; border: 0; border-radius: 10px; padding: 12px 16px; font-weight: 700; font-size: 16px; cursor: pointer; }}
button.ghost {{ background: rgba(255,255,255,.08); color: #fff; }}
.input-row {{ display: flex; gap: 8px; }}
.input-row input {{ flex: 1; min-width: 0; background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.12); color: #fff; padding: 10px 12px; border-radius: 10px; font-size: 15px; }}
.meta {{ font-size: 12px; color: rgba(255,255,255,.65); display: flex; flex-wrap: wrap; gap: 12px; }}
.banner {{ position: absolute; top: 0; left: 0; right: 0; padding: 12px 16px; background: rgba(255,80,80,.92); color: #fff; font-size: 14px; display: none; }}
.idle {{ position: absolute; inset: 0; display: grid; place-items: center; padding: 24px; text-align: center; }}
.idle h2 {{ font-size: 22px; margin: 0 0 6px; }}
.idle p {{ color: rgba(255,255,255,.7); margin: 0 0 22px; max-width: 360px; }}
</style>
</head>
<body>
<div class="shell">
  <div class="banner" id="banner"></div>
  <video id="video" playsinline autoplay muted></video>
  <div class="controls">
    <div class="row">
      <div class="dot" id="dot"></div>
      <div style="flex:1;">
        <div id="title" style="font-weight:600;">Tap start to share this camera</div>
        <div class="meta"><span id="metaState">idle</span><span id="metaToken">token <b>{token_safe}</b></span><span id="metaFps">0 fps</span></div>
      </div>
    </div>
    <div class="input-row">
      <input id="labelInput" value="{label_safe}" placeholder="Label this camera (e.g. Front porch)">
      <button id="startBtn">Start</button>
      <button id="flipBtn" class="ghost">Flip</button>
    </div>
  </div>
  <div class="idle" id="idle">
    <div>
      <h2>Third Eye on your phone</h2>
      <p>Tap <b>Start</b>, allow camera access, and prop your phone where you want SafeWatch to watch. The desktop pairing screen will turn green the moment frames arrive.</p>
    </div>
  </div>
</div>

<canvas id="canvas" hidden></canvas>
<script>
const TOKEN = "{token_safe}";
const WS_URL = "{ws_url_safe}";
const FPS = 8;
const QUALITY = 0.6;
const MAX_EDGE = 720;

const video = document.getElementById("video");
const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const startBtn = document.getElementById("startBtn");
const flipBtn = document.getElementById("flipBtn");
const dot = document.getElementById("dot");
const banner = document.getElementById("banner");
const idleScreen = document.getElementById("idle");
const labelInput = document.getElementById("labelInput");
const metaState = document.getElementById("metaState");
const metaFps = document.getElementById("metaFps");
const titleEl = document.getElementById("title");

let stream = null;
let ws = null;
let facing = "environment";
let sending = false;
let framesSent = 0;
let encodeInFlight = false;
let lastFpsAt = performance.now();
let lastFpsCount = 0;

function showError(msg) {{
  banner.textContent = msg;
  banner.style.display = "block";
}}

async function start() {{
  try {{
    stream = await navigator.mediaDevices.getUserMedia({{
      video: {{ facingMode: {{ ideal: facing }}, width: {{ ideal: 1280 }}, height: {{ ideal: 720 }} }},
      audio: false,
    }});
  }} catch (e) {{
    showError("Camera blocked: " + (e.message || e.name) + ". Open in Safari/Chrome and allow camera.");
    return;
  }}
  video.srcObject = stream;
  await video.play();
  idleScreen.style.display = "none";
  startBtn.textContent = "Stop";
  startBtn.onclick = stop;
  metaState.textContent = "connecting";
  titleEl.textContent = "Connecting to SafeWatch\u2026";
  connect();
  loop();
}}

function stop() {{
  sending = false;
  if (ws) {{ try {{ ws.close(); }} catch (e) {{}} ws = null; }}
  if (stream) {{ stream.getTracks().forEach(t => t.stop()); stream = null; }}
  startBtn.textContent = "Start";
  startBtn.onclick = start;
  dot.className = "dot";
  metaState.textContent = "idle";
  titleEl.textContent = "Stopped";
  idleScreen.style.display = "grid";
}}

function connect() {{
  const url = new URL(WS_URL, location.href);
  if (labelInput.value) url.searchParams.set("label", labelInput.value);
  ws = new WebSocket(url.toString());
  ws.binaryType = "arraybuffer";
  ws.onopen = () => {{
    sending = true;
    dot.className = "dot live";
    metaState.textContent = "streaming";
    titleEl.textContent = "Streaming · this phone is now a Third Eye";
  }};
  ws.onclose = () => {{
    sending = false;
    if (stream) {{
      // Try to reconnect after a short delay if the user is still streaming.
      dot.className = "dot";
      metaState.textContent = "reconnecting";
      titleEl.textContent = "Reconnecting\u2026";
      setTimeout(() => {{ if (stream) connect(); }}, 1200);
    }}
  }};
  ws.onerror = () => {{}};
}}

flipBtn.onclick = async () => {{
  facing = facing === "environment" ? "user" : "environment";
  if (stream) {{
    stream.getTracks().forEach(t => t.stop());
    stream = null;
    await start();
  }}
}};

function loop() {{
  if (!stream) return;
  if (encodeInFlight || (ws && ws.bufferedAmount > 1_000_000)) {{
    setTimeout(loop, 1000 / FPS);
    return;
  }}
  const w = video.videoWidth || 640;
  const h = video.videoHeight || 480;
  if (w && h) {{
    const scale = Math.min(1, MAX_EDGE / Math.max(w, h));
    const cw = Math.round(w * scale);
    const ch = Math.round(h * scale);
    if (canvas.width !== cw || canvas.height !== ch) {{
      canvas.width = cw; canvas.height = ch;
    }}
    ctx.drawImage(video, 0, 0, cw, ch);
    encodeInFlight = true;
    canvas.toBlob(async (blob) => {{
      try {{
        if (!blob || !sending || !ws || ws.readyState !== 1 || ws.bufferedAmount > 1_000_000) return;
        const buf = await blob.arrayBuffer();
        if (!sending || !ws || ws.readyState !== 1 || ws.bufferedAmount > 1_000_000) return;
        ws.send(buf);
        framesSent++;
      }} catch (e) {{}}
      finally {{
        encodeInFlight = false;
      }}
    }}, "image/jpeg", QUALITY);
  }}
  // FPS meter
  const now = performance.now();
  if (now - lastFpsAt > 1000) {{
    const fps = ((framesSent - lastFpsCount) * 1000 / (now - lastFpsAt));
    metaFps.textContent = fps.toFixed(1) + " fps";
    lastFpsCount = framesSent;
    lastFpsAt = now;
  }}
  setTimeout(loop, 1000 / FPS);
}}

startBtn.onclick = start;

// Keep the screen awake while streaming (best-effort, modern browsers).
let wake = null;
async function lockWake() {{
  try {{ if ("wakeLock" in navigator) wake = await navigator.wakeLock.request("screen"); }} catch (e) {{}}
}}
document.addEventListener("visibilitychange", () => {{
  if (document.visibilityState === "visible" && !wake) lockWake();
}});
lockWake();
</script>
</body>
</html>"""
