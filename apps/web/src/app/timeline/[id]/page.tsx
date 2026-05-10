"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Play } from "lucide-react";
import { SeverityBadge } from "@safewatch/ui/web";
import { getEvent } from "@/lib/api";
import type { EventRecord } from "@safewatch/api-types";

export default function EventDetail() {
  const params = useParams<{ id: string }>();
  const [ev, setEv] = useState<EventRecord | null>(null);
  useEffect(() => {
    if (params.id) getEvent(params.id).then(setEv).catch(() => setEv(null));
  }, [params.id]);

  if (!ev) {
    return (
      <div className="font-mono text-[12px] uppercase tracking-[0.22em] text-maroon-200/70">
        loading…
      </div>
    );
  }

  return (
    <>
      <Link
        href="/timeline"
        className="inline-flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/80 hover:text-cream-50"
      >
        <ArrowLeft className="h-3 w-3" /> Timeline
      </Link>

      <header className="mt-4 mb-8">
        <SeverityBadge tier={ev.tier} />
        <h1 className="mt-3 font-serif text-[44px] leading-tight text-cream-50 max-w-[34ch] text-balance">
          {ev.one_line_summary}
        </h1>
        <p className="mt-3 font-mono text-[12px] text-cream-50/60">
          {new Date(ev.timestamp).toLocaleString()} · {ev.scene} · confidence{" "}
          <span className="text-cream-50">
            {(ev.confidence * 100).toFixed(0)}%
          </span>
        </p>
      </header>

      <div className="grid gap-5 md:grid-cols-[1.2fr_1fr]">
        <div className="relative overflow-hidden rounded-2xl ring-glow border border-maroon-300/15">
          <div
            className="aspect-[16/10] w-full"
            style={{
              background:
                "radial-gradient(circle at 30% 30%, #9A3142 0%, #5E1521 35%, #1F050A 75%, #0A0103 100%)",
            }}
          />
          <div className="absolute top-3 left-4 font-mono text-[10.5px] uppercase tracking-[0.22em] text-cream-50/70">
            CLIP · {ev.id} · 8.4s
          </div>
          <button className="absolute bottom-4 right-4 inline-flex items-center gap-1.5 rounded-full bg-cream-50/95 px-4 py-2 text-[12.5px] font-medium text-maroon-900 hover:bg-cream-100">
            <Play className="h-3 w-3" /> Play
          </button>
        </div>

        <div className="grid gap-3">
          <div className="card-glass ring-glow rounded-xl p-5">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/80">
              AI description
            </div>
            <p className="mt-2 text-[14.5px] text-cream-50/85">
              {ev.suspect_description ?? ev.one_line_summary}
            </p>
          </div>

          <div className="card-glass ring-glow rounded-xl p-5">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/80">
              Detected
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {ev.yolo_classes.map((c) => (
                <span
                  key={c}
                  className="rounded-md bg-maroon-200/10 px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.14em] text-cream-50/80"
                >
                  {c}
                </span>
              ))}
            </div>
          </div>

          <div className="card-glass ring-glow rounded-xl p-5">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/80">
              Actions taken
            </div>
            <ul className="mt-2 space-y-1 text-[13.5px] text-cream-50/85">
              {ev.actions_taken.length === 0 && (
                <li className="text-cream-50/45">None - logged only</li>
              )}
              {ev.actions_taken.map((a) => (
                <li key={a}>{a.replace(/_/g, " ")}</li>
              ))}
            </ul>
          </div>

          <div className="flex flex-wrap gap-2">
            <button className="rounded-full bg-cream-50 px-4 py-2 text-[12.5px] font-medium text-maroon-900 hover:bg-cream-100">
              Acknowledge
            </button>
            <button className="rounded-full border border-maroon-300/30 px-4 py-2 text-[12.5px] text-cream-50 hover:bg-maroon-300/10">
              Escalate
            </button>
            <button className="rounded-full border border-maroon-300/30 px-4 py-2 text-[12.5px] text-cream-50 hover:bg-maroon-300/10">
              Mark false alarm
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
