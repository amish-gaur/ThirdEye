import type {
  EventRecord,
  NodeSummary,
  ContactRule,
  PairingChallenge,
  QueryStreamEvent,
} from "@safewatch/api-types";

const base = "/api";

/**
 * Public base URL for action-router static assets (the JPEG suspect
 * frames live at `${PUBLIC_BASE_URL}/media/frames/<basename>`).
 *
 * Configure via `NEXT_PUBLIC_PUBLIC_BASE_URL` in `.env.local`. ngrok
 * URLs reroll on free-tier restarts, so never hard-code one.
 */
export const PUBLIC_BASE_URL: string =
  (typeof process !== "undefined" &&
    process.env.NEXT_PUBLIC_PUBLIC_BASE_URL) ||
  "";

/**
 * Resolve the suspect-frame URL for an event.
 *
 * Prefers a server-rendered `clip_url`. Falls back to deriving one from
 * the disk path the action router writes for tier 3/4 incidents:
 *   `/.../media/frames/inc_<id>_<unix_ts>.jpg`
 *   -> `${PUBLIC_BASE_URL}/media/frames/inc_<id>_<unix_ts>.jpg`
 *
 * Returns `null` for events that have no frame (tier 1/2 don't get one).
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

export async function getEvents(tier?: number): Promise<EventRecord[]> {
  const url = new URL(`${base}/events`, window.location.origin);
  if (tier) url.searchParams.set("tier", String(tier));
  const r = await fetch(url);
  const j = await r.json();
  return j.events as EventRecord[];
}

export async function getEvent(id: string): Promise<EventRecord> {
  const r = await fetch(`${base}/events/${id}`);
  if (!r.ok) throw new Error("not found");
  return (await r.json()) as EventRecord;
}

export async function getNodes(): Promise<NodeSummary[]> {
  const r = await fetch(`${base}/nodes`);
  const j = await r.json();
  return j.nodes as NodeSummary[];
}

export async function getContacts(): Promise<ContactRule[]> {
  const r = await fetch(`${base}/contacts`);
  const j = await r.json();
  return j.contacts as ContactRule[];
}

export async function startPairing(): Promise<PairingChallenge> {
  const r = await fetch(`${base}/pair`, { method: "POST" });
  return (await r.json()) as PairingChallenge;
}

export async function streamQuery(
  question: string,
  onEvent: (e: QueryStreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const r = await fetch(`${base}/query`, {
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
