import { http, HttpResponse, delay } from "msw";
import { events, nodes, contacts } from "./fixtures";

const API = "/api";

export const handlers = [
  http.get(`${API}/nodes`, async () => {
    await delay(80);
    return HttpResponse.json({ nodes });
  }),
  http.get(`${API}/events`, async ({ request }) => {
    await delay(120);
    const url = new URL(request.url);
    const tier = url.searchParams.get("tier");
    const filtered = tier
      ? events.filter((e) => String(e.tier) === tier)
      : events;
    return HttpResponse.json({ events: filtered });
  }),
  http.get(`${API}/events/:id`, async ({ params }) => {
    await delay(100);
    const ev = events.find((e) => e.id === params.id);
    if (!ev) return new HttpResponse(null, { status: 404 });
    return HttpResponse.json(ev);
  }),
  http.get(`${API}/contacts`, async () => {
    await delay(60);
    return HttpResponse.json({ contacts });
  }),
  http.post(`${API}/pair`, async () => {
    await delay(180);
    const code = Math.random().toString(36).slice(2, 8).toUpperCase();
    return HttpResponse.json({
      pair_code: code,
      expires_at: new Date(Date.now() + 5 * 60_000).toISOString(),
      qr_payload: `safewatch://pair?code=${code}`,
    });
  }),
  http.post(`${API}/query`, async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as {
      question?: string;
    };
    const question = body.question ?? "";
    const stream = new ReadableStream({
      async start(controller) {
        const encoder = new TextEncoder();
        const send = (obj: unknown) =>
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(obj)}\n\n`));
        const tokens = answerFor(question).split(" ");
        for (const t of tokens) {
          await delay(35);
          send({ type: "token", text: t + " " });
        }
        const cited = events.slice(0, 2).map((e) => ({
          type: "clip",
          clip: {
            event_id: e.id,
            thumb_url: e.thumb_url,
            timestamp: e.timestamp,
            tier: e.tier,
            one_line: e.one_line_summary,
          },
        }));
        for (const c of cited) {
          await delay(80);
          send(c);
        }
        send({ type: "done" });
        controller.close();
      },
    });
    return new HttpResponse(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
      },
    });
  }),
];

function answerFor(q: string): string {
  const lower = q.toLowerCase();
  if (lower.includes("porch") || lower.includes("package")) {
    return "Yes — two events at the front porch in the last few hours: a delivery 2 hours ago and a package pickup 2 minutes ago that triggered an Alert.";
  }
  if (lower.includes("driveway") || lower.includes("car")) {
    return "Driveway has been quiet since a vehicle arrived ~5 hours ago. One loitering Notice 34 minutes ago near the side gate.";
  }
  return "I scanned the last 24 hours of events. Nothing critical right now; one Alert at the front porch 2 minutes ago is the most recent item worth attention.";
}
