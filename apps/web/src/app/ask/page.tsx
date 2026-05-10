"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Sparkles } from "lucide-react";
import { SeverityBadge } from "@safewatch/ui/web";
import { Aurora } from "@/components/magic/Aurora";
import { ShimmerText } from "@/components/magic/ShimmerText";
import { streamQuery } from "@/lib/api";
import { embedText, ensureLoaded, subscribe } from "@/lib/edgeInference";
import type { QueryStreamEvent, Tier } from "@safewatch/api-types";

type Msg = {
  role: "user" | "assistant";
  text: string;
  clips: { event_id: string; timestamp: string; tier: Tier; one_line: string }[];
  embeddingDims?: number;
};

const SUGGESTIONS = [
  "Anyone come to the porch in the last hour?",
  "Show me the driveway around 2pm",
  "Was there a delivery today?",
  "Is the side gate clear right now?",
];

export default function AskPage() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [edgeStatus, setEdgeStatus] = useState<string>("idle");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    return subscribe((s: { status: string }) => setEdgeStatus(s.status));
  }, []);
  useEffect(() => {
    ensureLoaded();
  }, []);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 1e9, behavior: "smooth" });
  }, [messages]);

  async function send(question: string) {
    if (!question.trim() || busy) return;
    setBusy(true);
    setInput("");

    const userMsg: Msg = { role: "user", text: question, clips: [] };
    let dims: number | undefined;
    try {
      const v = await embedText(question);
      dims = v.length;
    } catch {}
    userMsg.embeddingDims = dims;

    const assistantMsg: Msg = { role: "assistant", text: "", clips: [] };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);

    await streamQuery(question, (e: QueryStreamEvent) => {
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (!last || last.role !== "assistant") return next;
        if (e.type === "token") {
          next[next.length - 1] = { ...last, text: last.text + e.text };
        } else if (e.type === "clip") {
          next[next.length - 1] = {
            ...last,
            clips: [...last.clips, e.clip],
          };
        }
        return next;
      });
    });
    setBusy(false);
  }

  return (
    <>
      <section className="relative overflow-hidden rounded-[28px] border border-maroon-300/10 bg-maroon-900/20 px-8 pt-12 pb-10 mb-6 ring-glow">
        <Aurora />
        <div className="relative z-[2] max-w-[680px]">
          <div className="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-[0.24em] text-maroon-200/80">
            <Sparkles className="h-3 w-3" /> Ask
          </div>
          <h1 className="mt-4 font-serif text-[58px] leading-[1.02] text-cream-50 text-balance">
            What do you <ShimmerText>want to know</ShimmerText>?
          </h1>
          <p className="mt-5 text-[15.5px] text-cream-50/65">
            Your question is embedded with CLIP <em className="text-cream-50">in this browser</em>.
            Only the vector goes to the brain. Never the words.
          </p>
        </div>
      </section>

      <div
        ref={scrollRef}
        className="card-glass ring-glow rounded-2xl p-6 min-h-[420px] max-h-[55vh] overflow-y-auto grid gap-3"
      >
        {messages.length === 0 && (
          <div className="grid gap-2">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/70">
              Try
            </div>
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="text-left rounded-xl border border-maroon-300/15 bg-maroon-950/30 px-4 py-3 font-serif text-[17px] text-cream-50/90 hover:bg-maroon-300/10 hover:border-maroon-200/30 transition-colors"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {messages.map((m, i) => (
          <div
            key={i}
            className={
              "flex flex-col " +
              (m.role === "user" ? "items-end" : "items-start")
            }
          >
            <div
              className={
                m.role === "user"
                  ? "rounded-2xl bg-cream-50 px-5 py-3 max-w-[78%] font-serif text-[17px] text-maroon-900"
                  : "rounded-2xl border border-maroon-300/15 bg-maroon-950/40 px-5 py-3 max-w-[78%] text-[15px] text-cream-50/90"
              }
            >
              {m.text || (m.role === "assistant" && busy ? "…" : null)}
            </div>
            {m.embeddingDims !== undefined && m.role === "user" && (
              <div className="mt-1 font-mono text-[10px] text-cream-50/45">
                embedded locally · {m.embeddingDims}-dim · 0 bytes uploaded
              </div>
            )}
            {m.clips.length > 0 && (
              <div className="mt-2 grid w-full gap-2 sm:grid-cols-2">
                {m.clips.map((c) => (
                  <Link
                    key={c.event_id}
                    href={`/timeline/${c.event_id}`}
                    className="card-glass ring-glow flex items-center gap-3 rounded-xl px-3 py-2 hover:-translate-y-px transition-transform"
                  >
                    <div
                      className="h-12 w-16 shrink-0 rounded-md"
                      style={{
                        background:
                          "linear-gradient(135deg, #1F050A 0%, #5E1521 60%, #9A3142 100%)",
                      }}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px] text-cream-50">
                        {c.one_line}
                      </div>
                      <div className="font-mono text-[11px] text-cream-50/55">
                        {new Date(c.timestamp).toLocaleTimeString()}
                      </div>
                    </div>
                    <SeverityBadge tier={c.tier} />
                  </Link>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="mt-4 flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask anything about the last 24 hours…"
          className="flex-1 rounded-full border border-maroon-300/20 bg-maroon-950/60 px-5 py-3 font-serif text-[16px] text-cream-50 placeholder:text-cream-50/35 focus:border-maroon-200/50 focus:outline-none"
        />
        <button
          disabled={busy}
          className="rounded-full bg-cream-50 px-6 text-[14px] font-medium text-maroon-900 disabled:opacity-40 hover:bg-cream-100"
        >
          {busy ? "…" : "Ask"}
        </button>
      </form>
      <div className="mt-2 font-mono text-[10.5px] text-cream-50/40">
        edge model: {edgeStatus}
      </div>
    </>
  );
}
