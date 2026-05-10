import type {
  EventRecord,
  NodeSummary,
  ContactRule,
  PairingChallenge,
  QueryStreamEvent,
} from "@safewatch/api-types";

const base = "/api";

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
