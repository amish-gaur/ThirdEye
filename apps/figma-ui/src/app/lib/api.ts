// Backend wiring for the action_router service.
//
// Override at build time with VITE_BACKEND_URL=http://host:8001. Default points
// at the dev box where action_router runs (uvicorn action_router.service:app
// --host 0.0.0.0 --port 8001).

export const BACKEND_URL =
  (import.meta as any).env?.VITE_BACKEND_URL ?? "http://127.0.0.1:8001";

/**
 * Public base URL the action router exposes static assets at
 * (`${PUBLIC_BASE_URL}/media/frames/<basename>.jpg`).
 *
 * Override with `VITE_PUBLIC_BASE_URL=https://<your-ngrok>.ngrok-free.app`.
 * Defaults to BACKEND_URL so local dev (everything on :8001) works without
 * extra config. Free-tier ngrok URLs reroll on restart - never hard-code.
 */
export const PUBLIC_BASE_URL: string =
  (import.meta as any).env?.VITE_PUBLIC_BASE_URL ?? BACKEND_URL;

/**
 * Resolve the suspect-frame URL for an incident event.
 *
 * Prefers a server-rendered `clip_url`. Falls back to deriving one from the
 * action router's disk path: `/.../media/frames/inc_<id>_<unix_ts>.jpg`
 *   -> `${PUBLIC_BASE_URL}/media/frames/inc_<id>_<unix_ts>.jpg`
 *
 * Returns `null` for events that have no frame (tier 1/2 don't get one).
 */
export function suspectFrameUrl(
  ev: Pick<IncidentEvent, "clip_url" | "clip_path"> | undefined | null
): string | null {
  if (!ev) return null;
  if (ev.clip_url) return ev.clip_url;
  if (!ev.clip_path) return null;
  const basename = ev.clip_path.split("/").pop();
  if (!basename) return null;
  return `${PUBLIC_BASE_URL.replace(/\/$/, "")}/media/frames/${basename}`;
}

export type Tier = "ambient" | "notice" | "alert" | "emergency";

export type IncidentEvent = {
  event_id?: string;
  incident_id?: string;
  node_id?: string;
  tier?: number;
  tier_name?: string;
  one_line_summary?: string;
  suspect_description?: string;
  scene?: string;
  timestamp?: number;
  behavior_pattern?: string;
  /** Server-rendered absolute URL for the suspect frame (preferred). */
  clip_url?: string;
  /**
   * Disk path the action router writes for tier-3/4 incidents
   * (`/.../media/frames/inc_<id>_<unix_ts>.jpg`). The client takes
   * the basename and joins it with PUBLIC_BASE_URL to fetch from
   * `/media/frames/<basename>`.
   */
  clip_path?: string;
};

export type StreamMessage = {
  event: IncidentEvent;
  result: { tier: number; tier_label: string; actions: string[]; duplicate: boolean };
};

export type CameraEntry = {
  node_id: string;
  name: string;
  stream_url: string;
  status: "warming" | "running" | "crashed";
  pid: number;
  started_at: number;
  ready_at: number | null;
};

export function tierFromName(name: string | undefined): Tier {
  const n = (name ?? "").toLowerCase();
  if (n === "emergency" || n === "alert" || n === "notice" || n === "ambient") return n;
  return "ambient";
}

export function statusFromEntry(s: string): "live" | "idle" | "alert" {
  if (s === "running") return "live";
  if (s === "crashed") return "alert";
  return "idle";
}

export function formatTime(ts: number | undefined): string {
  if (!ts) return "--:--";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export async function fetchCameras(): Promise<CameraEntry[]> {
  try {
    const r = await fetch(`${BACKEND_URL}/api/cameras`);
    if (!r.ok) return [];
    return (await r.json()) as CameraEntry[];
  } catch {
    return [];
  }
}

export function streamUrlForToken(streamUrl: string): string {
  // The registry stores the upstream MJPEG URL directly (e.g. the phone-camera
  // MJPEG endpoint or an mDNS-discovered cam). Browser <img> renders MJPEG
  // natively, so this is the URL to drop in.
  return streamUrl;
}

// ─── Backend health ──────────────────────────────────────────────────────

export type BackendHealth = {
  status: string;
  dry_run: boolean;
  use_claude: boolean;
  use_elevenlabs: boolean;
  elevenlabs_play_enabled: boolean;
  public_base_url?: string | null;
  twilio_configured: boolean;
};

export async function fetchHealth(): Promise<BackendHealth | null> {
  try {
    const r = await fetch(`${BACKEND_URL}/health`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as BackendHealth;
  } catch {
    return null;
  }
}

// ─── Warmup (Qwen + YOLO readiness) ──────────────────────────────────────

export type WarmupStatus = {
  state: "cold" | "warming" | "ready";
  elapsed_s: number;
  running: number;
  warming: number;
  crashed: number;
};

export async function fetchWarmup(): Promise<WarmupStatus | null> {
  try {
    const r = await fetch(`${BACKEND_URL}/api/warmup`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as WarmupStatus;
  } catch {
    return null;
  }
}

// ─── Identity (phone → web handoff) ─────────────────────────────────────

export type IdentitySession = {
  session_id: string;
  code: string;
  name: string;
  email: string;
  device_id?: string | null;
  status: "pending" | "claimed";
  created_at: number;
  claimed_at: number | null;
};

export async function fetchIdentityByCode(code: string): Promise<IdentitySession | null> {
  const c = code.trim().toUpperCase();
  if (!c) return null;
  try {
    const r = await fetch(`${BACKEND_URL}/api/identity/by-code/${encodeURIComponent(c)}`, {
      cache: "no-store",
    });
    if (!r.ok) return null;
    return (await r.json()) as IdentitySession;
  } catch {
    return null;
  }
}

export async function claimIdentity(code: string): Promise<IdentitySession | null> {
  const c = code.trim().toUpperCase();
  if (!c) return null;
  try {
    const r = await fetch(
      `${BACKEND_URL}/api/identity/by-code/${encodeURIComponent(c)}/claim`,
      { method: "POST" }
    );
    if (!r.ok) return null;
    return (await r.json()) as IdentitySession;
  } catch {
    return null;
  }
}

// ─── LAN discovery + camera registry mutations ──────────────────────────

export type DiscoveredCamera = {
  name: string;
  host: string;
  port: number;
  stream_url: string;
  source_protocol?: string;
};

export async function discoverCameras(timeout = 3.0): Promise<DiscoveredCamera[]> {
  try {
    const r = await fetch(
      `${BACKEND_URL}/api/discover?timeout=${encodeURIComponent(timeout)}`,
      { cache: "no-store" }
    );
    if (!r.ok) return [];
    return (await r.json()) as DiscoveredCamera[];
  } catch {
    return [];
  }
}

export async function addCamera(name: string, stream_url: string): Promise<CameraEntry | null> {
  try {
    const r = await fetch(`${BACKEND_URL}/api/cameras/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, stream_url }),
    });
    if (!r.ok) return null;
    return (await r.json()) as CameraEntry;
  } catch {
    return null;
  }
}
