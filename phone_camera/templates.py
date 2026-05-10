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
    """Phone capture page: getUserMedia + WebSocket frame upload.

    Re-skinned to match the Third Eye Figma Make design system —
    cream/ink palette, thick black borders, offset block shadows,
    Playfair Display + DM Mono. JS behaviour and every element ID
    are preserved exactly so the existing handlers keep working.
    """
    token_safe = _esc(token)
    ws_url_safe = _esc(ws_url)
    label_safe = _esc(label_default)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f4ead8">
<title>Third Eye · phone camera</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Playfair+Display:ital,wght@0,700;0,900;1,700;1,900&family=Inter:wght@500;600;700&display=swap" rel="stylesheet">
<style>
:root {{
  --cream: #f4ead8;
  --ink: #1a0306;
  --red: #c8222d;
  --orange: #e85a3c;
  --gold: #f4c97a;
  --wine: #7a2230;
  --deep: #3a1014;
  --sand: #e6d2a8;
}}
* {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
html, body {{ margin: 0; padding: 0; height: 100dvh; height: 100vh; background: var(--cream); color: var(--ink); font: 15px/1.4 "Inter", -apple-system, BlinkMacSystemFont, system-ui, sans-serif; overscroll-behavior: none; }}
body::before, body::after {{ content: ""; position: fixed; pointer-events: none; z-index: 0; border-radius: 50%; border: 4px solid var(--ink); }}
body::before {{ width: 280px; height: 280px; top: -120px; right: -90px; background: var(--gold); }}
body::after {{ width: 360px; height: 360px; bottom: -180px; left: -140px; background: var(--orange); opacity: .55; }}

.shell {{ position: fixed; inset: 0; display: flex; flex-direction: column; z-index: 1; }}
video {{ flex: 1 1 auto; min-height: 0; width: 100%; object-fit: cover; background: var(--ink); display: block; }}

/* ---------- Top wordmark strip (visible whenever the camera area is showing) ---------- */
.brand-strip {{
  position: absolute; top: max(14px, env(safe-area-inset-top)); left: 16px; right: 16px;
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  z-index: 4; pointer-events: none;
}}
.brand {{
  background: var(--cream); color: var(--ink);
  border: 3px solid var(--ink); border-radius: 999px;
  padding: 8px 14px; box-shadow: 0 4px 0 var(--ink);
  font-family: "Playfair Display", serif; font-weight: 900; font-size: 18px; line-height: 1;
  letter-spacing: -0.01em;
}}
.brand i {{ color: var(--red); font-style: italic; font-weight: 900; }}
.token-pill {{
  background: var(--gold); color: var(--ink);
  border: 3px solid var(--ink); border-radius: 999px;
  padding: 6px 12px; box-shadow: 0 4px 0 var(--ink);
  font-family: "DM Mono", ui-monospace, monospace; font-size: 10px; letter-spacing: 0.25em;
  text-transform: uppercase;
}}

/* ---------- Bottom controls card ---------- */
.controls {{
  position: relative; z-index: 3;
  margin: 0 12px max(14px, env(safe-area-inset-bottom));
  background: var(--cream);
  border: 4px solid var(--ink); border-radius: 18px;
  box-shadow: 0 6px 0 var(--ink);
  padding: 14px 16px 16px;
  display: grid; gap: 12px;
}}
.row {{ display: flex; align-items: center; gap: 12px; }}
.dot {{
  width: 14px; height: 14px; border-radius: 50%;
  background: var(--gold); border: 3px solid var(--ink);
  flex: 0 0 14px; transition: background .2s;
}}
.dot.live {{ background: var(--red); animation: pulse 1.4s ease-in-out infinite; }}
@keyframes pulse {{ 0%, 100% {{ transform: scale(1); }} 50% {{ transform: scale(1.25); }} }}
#title {{
  font-family: "DM Mono", ui-monospace, monospace;
  font-size: 12px; letter-spacing: 0.18em; text-transform: uppercase;
  color: var(--ink); font-weight: 500;
}}
.meta {{
  font-family: "DM Mono", ui-monospace, monospace;
  font-size: 10px; letter-spacing: 0.18em; text-transform: uppercase;
  color: var(--deep);
  display: flex; flex-wrap: wrap; gap: 10px; margin-top: 4px;
}}
.meta b {{ color: var(--ink); font-weight: 500; }}

.input-row {{ display: flex; gap: 8px; align-items: stretch; }}
.input-row input {{
  flex: 1; min-width: 0;
  background: var(--cream); color: var(--ink);
  border: 3px solid var(--ink); border-radius: 10px;
  padding: 10px 12px; font: 14px/1.3 "Inter", system-ui, sans-serif;
  box-shadow: 0 3px 0 var(--ink);
}}
.input-row input::placeholder {{ color: var(--deep); opacity: .55; }}

button {{
  font-family: "DM Mono", ui-monospace, monospace;
  font-size: 12px; letter-spacing: 0.2em; text-transform: uppercase;
  background: var(--red); color: var(--cream);
  border: 3px solid var(--ink); border-radius: 999px;
  padding: 12px 18px; font-weight: 600;
  cursor: pointer; box-shadow: 0 4px 0 var(--ink);
  transition: transform .08s ease, box-shadow .08s ease;
}}
button:active {{ transform: translateY(2px); box-shadow: 0 2px 0 var(--ink); }}
button.ghost {{ background: var(--cream); color: var(--ink); }}

.banner {{
  position: absolute; top: max(14px, env(safe-area-inset-top)); left: 16px; right: 16px;
  z-index: 5;
  background: var(--red); color: var(--cream);
  border: 4px solid var(--ink); border-radius: 14px;
  box-shadow: 0 5px 0 var(--ink);
  padding: 12px 14px;
  font-family: "DM Mono", ui-monospace, monospace;
  font-size: 12px; letter-spacing: 0.08em;
  display: none;
}}

/* ---------- Idle / hero (covers the camera before it starts) ---------- */
.idle {{
  position: absolute; inset: 0; z-index: 2;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 32px 22px; text-align: center; gap: 18px;
  background: var(--cream);
}}
.idle .eyebrow {{
  font-family: "DM Mono", ui-monospace, monospace;
  font-size: 10px; letter-spacing: 0.4em; text-transform: uppercase;
  color: var(--deep); display: flex; align-items: center; gap: 8px;
}}
.idle .eyebrow .pip {{ width: 8px; height: 8px; border-radius: 50%; background: var(--red); border: 2px solid var(--ink); display: inline-block; }}
.idle h1 {{
  font-family: "Playfair Display", serif; font-weight: 900;
  font-size: 44px; line-height: 1.02; letter-spacing: -0.01em;
  color: var(--ink); margin: 0;
}}
.idle h1 i {{ color: var(--red); font-style: italic; font-weight: 900; }}
.idle p {{
  color: var(--deep); margin: 0; max-width: 320px;
  font-size: 14px; line-height: 1.6;
}}
.cta {{ margin-top: 6px; font-size: 14px; padding: 16px 26px; }}
.idle .token-line {{
  font-family: "DM Mono", ui-monospace, monospace;
  font-size: 10px; letter-spacing: 0.3em; text-transform: uppercase;
  color: var(--wine);
}}
.idle .token-line b {{ color: var(--ink); }}

/* Stat tile row in idle */
.tier-row {{
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px;
  width: 100%; max-width: 360px; margin-top: 4px;
}}
.tier {{
  border: 3px solid var(--ink); border-radius: 8px;
  padding: 6px 4px; box-shadow: 0 3px 0 var(--ink);
  font-family: "DM Mono", ui-monospace, monospace;
  font-size: 8px; letter-spacing: 0.18em; text-transform: uppercase;
  color: var(--ink); text-align: center;
}}
.tier.t-amb {{ background: #cfc4a6; }}
.tier.t-not {{ background: var(--gold); }}
.tier.t-alr {{ background: var(--orange); color: var(--cream); }}
.tier.t-emr {{ background: var(--red); color: var(--cream); }}

/* When streaming, hide the brand strip's pointer-events so taps pass through */
.streaming .idle {{ display: none; }}
</style>
</head>
<body>
<div class="shell" id="shell">
  <div class="banner" id="banner"></div>

  <div class="brand-strip">
    <div class="brand">Third <i>Eye</i></div>
    <div class="token-pill">node · {token_safe}</div>
  </div>

  <video id="video" playsinline autoplay muted></video>

  <div class="controls">
    <div class="row">
      <div class="dot" id="dot"></div>
      <div style="flex:1; min-width: 0;">
        <div id="title">Tap start to share this camera</div>
        <div class="meta">
          <span id="metaState">idle</span>
          <span id="metaToken">token <b>{token_safe}</b></span>
          <span id="metaFps">0 fps</span>
        </div>
      </div>
    </div>
    <div class="input-row">
      <input id="labelInput" value="{label_safe}" placeholder="Label this camera (e.g. Front porch)">
      <button id="startBtn">Start</button>
      <button id="flipBtn" class="ghost">Flip</button>
    </div>
  </div>

  <div class="idle" id="idle">
    <div class="eyebrow"><span class="pip"></span> Phone · Third Eye sensor</div>
    <h1>Become a<br>Third <i>Eye</i>.</h1>
    <p>Tap below, allow camera access, and prop your phone where you want SafeWatch to watch. The desktop pairing screen turns green the moment frames arrive.</p>
    <button class="cta" id="heroStartBtn">Start camera</button>
    <div class="tier-row">
      <div class="tier t-amb">Ambient</div>
      <div class="tier t-not">Notice</div>
      <div class="tier t-alr">Alert</div>
      <div class="tier t-emr">Emerg</div>
    </div>
    <div class="token-line">token <b>{token_safe}</b> · frames stay on-device</div>
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
const heroStartBtn = document.getElementById("heroStartBtn");
const flipBtn = document.getElementById("flipBtn");
const dot = document.getElementById("dot");
const banner = document.getElementById("banner");
const shell = document.getElementById("shell");
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
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {{
    showError("This browser can't access the camera. Open the page in Safari or Chrome over HTTPS.");
    return;
  }}
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
  shell.classList.add("streaming");
  idleScreen.style.display = "none";
  startBtn.textContent = "Stop";
  startBtn.onclick = stop;
  metaState.textContent = "connecting";
  titleEl.textContent = "Connecting to SafeWatch\u2026";
  banner.style.display = "none";
  lockWake();
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
  titleEl.textContent = "Tap start to share this camera";
  shell.classList.remove("streaming");
  idleScreen.style.display = "";
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
if (heroStartBtn) heroStartBtn.addEventListener("click", start);

if (location.protocol !== "https:" && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {{
  showError("Camera requires HTTPS. Open this page over the public ngrok URL, not the LAN IP.");
}}

let wake = null;
async function lockWake() {{
  try {{ if ("wakeLock" in navigator) wake = await navigator.wakeLock.request("screen"); }} catch (e) {{}}
}}
document.addEventListener("visibilitychange", () => {{
  if (document.visibilityState === "visible" && !wake) lockWake();
}});
</script>
</body>
</html>"""
