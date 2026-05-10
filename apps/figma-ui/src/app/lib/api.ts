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
