import type {
  EventRecord,
  NodeSummary,
  ContactRule,
  PairingChallenge,
  QueryStreamEvent,
} from "@safewatch/api-types";
import { BACKEND_URL, USE_MOCKS, backendUrl } from "./config";

/**
 * Real backend lives on the action router. The web app talks to it
 * directly (CORS is wide open in `action_router/service.py`). A small
 * subset of endpoints — pairing QR codes, the contacts editor, the Ask
 * page demo — has no backend implementation yet, so those stay on the
 * MSW mocks served at `/api/*`. Resolver functions below pick the right
 * destination per endpoint instead of routing everything through `/api`.
 */
const MOCK_BASE = "/api";

/**
 * Public base URL for action-router static assets (the JPEG suspect
 * frames live at `${PUBLIC_BASE_URL}/media/frames/<basename>`).
 *
 * Falls back to the resolved backend URL so a single `NEXT_PUBLIC_BACKEND_URL`
 * is enough — separate `NEXT_PUBLIC_PUBLIC_BASE_URL` is only needed when
 * frames are served from a different origin (e.g. ngrok during demos).
 */
export const PUBLIC_BASE_URL: string =
  (typeof process !== "undefined" &&
    (process.env.NEXT_PUBLIC_PUBLIC_BASE_URL || "")) ||
  BACKEND_URL;

/**
 * Resolve the suspect-frame URL for an event. Prefers a server-rendered
 * `clip_url`; falls back to `${PUBLIC_BASE_URL}/media/frames/<basename>`
 * derived from the disk path the action router writes for tier 3/4
 * incidents. Returns `null` for events that have no frame.
 */
export function suspectFrameUrl(
  ev: Pick<EventRecord, "clip_url" | "clip_path">
): string | null {
  if (ev.clip_url) return ev.clip_url;
  if (!ev.clip_path) return null;
  const basename = ev.clip_path.split("/").pop();
  if (!basename) return null;
  if (!PUBLIC_BASE_URL) return null;
  return `${PUBLIC_BASE_URL.replace(/\/$/, "")}/media/frames/${basename}`;
}

// ─── Backend health ──────────────────────────────────────────────────────

export interface BackendHealth {
  status: string;
  dry_run: boolean;
  use_claude: boolean;
  use_elevenlabs: boolean;
  elevenlabs_play_enabled: boolean;
  public_base_url?: string | null;
  twilio_configured: boolean;
}

export async function fetchHealth(
  signal?: AbortSignal
): Promise<BackendHealth | null> {
  if (USE_MOCKS) {
    return {
      status: "ok",
      dry_run: true,
      use_claude: false,
      use_elevenlabs: false,
      elevenlabs_play_enabled: false,
      public_base_url: null,
      twilio_configured: false,
    };
  }
  try {
    const r = await fetch(backendUrl("/health"), {
      signal,
      cache: "no-store",
    });
    if (!r.ok) return null;
    return (await r.json()) as BackendHealth;
  } catch {
    return null;
  }
}

// ─── Camera registry (real backend) ──────────────────────────────────────

export interface CameraEntry {
  node_id: string;
  name: string;
  stream_url: string;
  pid: number;
  started_at: number;
  status: "warming" | "running" | "crashed";
  ready_at: number | null;
}

export interface DiscoveredCamera {
  name: string;
  host: string;
  port: number;
  stream_url: string;
  source_protocol?: string;
}

export async function fetchCameras(
  signal?: AbortSignal
): Promise<CameraEntry[]> {
  if (USE_MOCKS) return [];
  try {
    const r = await fetch(backendUrl("/api/cameras"), {
      signal,
      cache: "no-store",
    });
    if (!r.ok) return [];
    return (await r.json()) as CameraEntry[];
  } catch {
    return [];
  }
}

export async function discoverCameras(
  timeout = 3.0,
  signal?: AbortSignal
): Promise<DiscoveredCamera[]> {
  if (USE_MOCKS) return [];
  try {
    const r = await fetch(
      backendUrl(`/api/discover?timeout=${encodeURIComponent(timeout)}`),
      { signal, cache: "no-store" }
    );
    if (!r.ok) return [];
    return (await r.json()) as DiscoveredCamera[];
  } catch {
    return [];
  }
}

export async function addCamera(
  name: string,
  stream_url: string
): Promise<CameraEntry | null> {
  if (USE_MOCKS) return null;
  try {
    const r = await fetch(backendUrl("/api/cameras/add"), {
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

/**
 * Adapter — render the camera registry into the `NodeSummary` shape the
 * dashboard / live / settings views were originally written against.
 * `running` entries are "online"; `warming` are online-but-not-ready;
 * `crashed` are offline. We keep `stream_url` on the node so the live
 * tile can fall back to MJPEG when the user isn't on the brain Mac.
 */
export type LiveNode = NodeSummary & {
  stream_url?: string;
  registry_status?: CameraEntry["status"];
  ready_at?: number | null;
};

export function cameraToNode(c: CameraEntry): LiveNode {
  const isoFromUnix = (s: number) => new Date(s * 1000).toISOString();
  return {
    node_id: c.node_id,
    label: c.name || c.node_id,
    online: c.status !== "crashed",
    last_seen: isoFromUnix(c.ready_at ?? c.started_at),
    scene: c.name,
    stream_url: c.stream_url,
    registry_status: c.status,
    ready_at: c.ready_at,
  };
}

// ─── Incident SSE stream ─────────────────────────────────────────────────

/** Shape that lands on the wire from `/events/stream`. */
export interface IncidentStreamMessage {
  event?: {
    event_id?: string;
    incident_id?: string;
    node_id?: string;
    tier?: number;
    tier_label?: string;
    tier_name?: string;
    one_line_summary?: string;
    suspect_description?: string;
    scene?: string;
    timestamp?: number;
    behavior_pattern?: string;
    confidence?: number;
    yolo_classes?: string[];
    actions_taken?: string[];
    clip_path?: string;
    clip_url?: string;
    thumb_url?: string;
    homeowner_id?: string;
  };
  result?: {
    tier?: number;
    tier_label?: string;
    actions?: string[];
    duplicate?: boolean;
  };
}

/**
 * Subscribe to live incidents. Browser `EventSource` auto-reconnects, so
 * the only explicit cleanup is `close()` from the returned handle.
 *
 * Returns `null` when mocks are enabled — the dashboard falls back to
 * the in-memory fixtures so designers can still see the UI populated.
 */
export function subscribeIncidents(
  onMessage: (msg: IncidentStreamMessage) => void,
  onStatus?: (state: "open" | "error") => void
): { close: () => void } | null {
  if (USE_MOCKS) return null;
  if (typeof window === "undefined" || typeof EventSource === "undefined") {
    return null;
  }
  const es = new EventSource(backendUrl("/events/stream"));
  es.onopen = () => onStatus?.("open");
  es.onerror = () => onStatus?.("error");
  es.onmessage = (e) => {
    try {
      const obj = JSON.parse(e.data) as IncidentStreamMessage;
      onMessage(obj);
    } catch {
      /* keepalive comments arrive as zero-length frames; ignore */
    }
  };
  return {
    close: () => {
      try {
        es.close();
      } catch {
        /* noop */
      }
    },
  };
}

/**
 * Lift an SSE message into the `EventRecord` the existing UI consumes.
 * The action router's payload uses snake-case keys and a unix timestamp;
 * we normalize to ISO + the `tier_label` strings the SeverityBadge expects.
 */
export function streamMessageToEvent(
  msg: IncidentStreamMessage
): EventRecord | null {
  const ev = msg.event;
  if (!ev) return null;
  const ts = typeof ev.timestamp === "number" ? ev.timestamp : Date.now() / 1000;
  const tier = (msg.result?.tier ?? ev.tier ?? 1) as 1 | 2 | 3 | 4;
  const labelRaw =
    msg.result?.tier_label ?? ev.tier_label ?? ev.tier_name ?? "AMBIENT";
  const label = labelRaw.toUpperCase() as EventRecord["tier_label"];
  const id =
    ev.event_id ||
    ev.incident_id ||
    `evt_${Math.floor(ts)}_${Math.random().toString(36).slice(2, 6)}`;
  const incident_id = ev.incident_id || id;
  return {
    id,
    incident_id,
    node_id: ev.node_id || "node_unknown",
    homeowner_id: ev.homeowner_id || "self",
    tier,
    tier_label: label,
    behavior_pattern: ev.behavior_pattern || "unknown",
    confidence: ev.confidence ?? 0,
    scene: ev.scene || "",
    suspect_description: ev.suspect_description,
    one_line_summary:
      ev.one_line_summary ||
      ev.suspect_description ||
      "(incident received)",
    timestamp: new Date(ts * 1000).toISOString(),
    clip_path: ev.clip_path,
    clip_url: ev.clip_url,
    thumb_url: ev.thumb_url,
    yolo_classes: ev.yolo_classes ?? [],
    actions_taken: ev.actions_taken ?? msg.result?.actions ?? [],
  };
}

// ─── Identity (phone → web handoff) ─────────────────────────────────────

export interface IdentitySession {
  session_id: string;
  code: string;
  name: string;
  email: string;
  device_id?: string | null;
  status: "pending" | "claimed";
  created_at: number;
  claimed_at: number | null;
}

export async function fetchIdentityByCode(
  code: string
): Promise<IdentitySession | null> {
  const sanitized = code.trim().toUpperCase();
  if (!sanitized) return null;
  try {
    const r = await fetch(
      backendUrl(`/api/identity/by-code/${encodeURIComponent(sanitized)}`),
      { cache: "no-store" }
    );
    if (!r.ok) return null;
    return (await r.json()) as IdentitySession;
  } catch {
    return null;
  }
}

export async function claimIdentity(code: string): Promise<IdentitySession | null> {
  const sanitized = code.trim().toUpperCase();
  if (!sanitized) return null;
  try {
    const r = await fetch(
      backendUrl(`/api/identity/by-code/${encodeURIComponent(sanitized)}/claim`),
      { method: "POST" }
    );
    if (!r.ok) return null;
    return (await r.json()) as IdentitySession;
  } catch {
    return null;
  }
}

// ─── Warmup ─────────────────────────────────────────────────────────────

export interface WarmupStatus {
  state: "cold" | "warming" | "ready";
  elapsed_s: number;
  running: number;
  warming: number;
  crashed: number;
}

export async function fetchWarmup(
  signal?: AbortSignal
): Promise<WarmupStatus | null> {
  if (USE_MOCKS) {
    return { state: "ready", elapsed_s: 0, running: 1, warming: 0, crashed: 0 };
  }
  try {
    const r = await fetch(backendUrl("/api/warmup"), {
      signal,
      cache: "no-store",
    });
    if (!r.ok) return null;
    return (await r.json()) as WarmupStatus;
  } catch {
    return null;
  }
}

// ─── Legacy mock-backed endpoints ────────────────────────────────────────
// Pairing QR / contacts / Ask page have no backend yet; they stay on MSW.

export async function getEvents(tier?: number): Promise<EventRecord[]> {
  // When the real backend is up, the SSE store is the source of truth;
  // this fetch hits MSW for fixture data so a fresh page load still
  // shows something while the live stream populates.
  const url = new URL(`${MOCK_BASE}/events`, window.location.origin);
  if (tier) url.searchParams.set("tier", String(tier));
  const r = await fetch(url);
  if (!r.ok) return [];
  const j = await r.json();
  return (j.events ?? []) as EventRecord[];
}

export async function getEvent(id: string): Promise<EventRecord> {
  const r = await fetch(`${MOCK_BASE}/events/${id}`);
  if (!r.ok) throw new Error("not found");
  return (await r.json()) as EventRecord;
}

/**
 * Pull camera nodes for the dashboard. Real backend → registry adapter.
 * Falls back to MSW fixtures when mocks are on or when no cameras are
 * registered yet, so the dashboard never renders empty in dev.
 */
export async function getNodes(): Promise<NodeSummary[]> {
  if (!USE_MOCKS) {
    const cams = await fetchCameras();
    if (cams.length > 0) return cams.map(cameraToNode);
  }
  const r = await fetch(`${MOCK_BASE}/nodes`);
  if (!r.ok) return [];
  const j = await r.json();
  return (j.nodes ?? []) as NodeSummary[];
}

export async function getContacts(): Promise<ContactRule[]> {
  const r = await fetch(`${MOCK_BASE}/contacts`);
  if (!r.ok) return [];
  const j = await r.json();
  return (j.contacts ?? []) as ContactRule[];
}

export async function startPairing(): Promise<PairingChallenge> {
  const r = await fetch(`${MOCK_BASE}/pair`, { method: "POST" });
  return (await r.json()) as PairingChallenge;
}

export async function streamQuery(
  question: string,
  onEvent: (e: QueryStreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const r = await fetch(`${MOCK_BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
    signal,
  });
  if (!r.body) return;
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() ?? "";
    for (const p of parts) {
      const line = p.trim();
      if (!line.startsWith("data:")) continue;
      try {
        const obj = JSON.parse(line.slice(5).trim()) as QueryStreamEvent;
        onEvent(obj);
      } catch {
        /* ignore */
      }
    }
  }
}
