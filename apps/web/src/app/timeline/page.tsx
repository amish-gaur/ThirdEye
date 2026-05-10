"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { SeverityBadge } from "@safewatch/ui/web";
import { getEvents, suspectFrameUrl } from "@/lib/api";
import { useIncidents } from "@/lib/liveStore";
import { cn } from "@/lib/utils";
import type { EventRecord } from "@safewatch/api-types";

export default function TimelinePage() {
  const { incidents } = useIncidents();
  const [history, setHistory] = useState<EventRecord[]>([]);
  const [tier, setTier] = useState<number | null>(null);

  useEffect(() => {
    getEvents().then(setHistory).catch(() => setHistory([]));
  }, []);

  // Live SSE incidents on top, fixture history below; de-dupe by id so
  // a server-side replay of the latest event doesn't render twice.
  const events = useMemo(() => {
    const seen = new Set<string>();
    const merged: EventRecord[] = [];
    for (const e of [...incidents, ...history]) {
      if (seen.has(e.id)) continue;
      seen.add(e.id);
      merged.push(e);
    }
    return merged;
  }, [incidents, history]);

  const filtered = useMemo(
    () => (tier ? events.filter((e) => e.tier === tier) : events),
    [events, tier]
  );

  const byDay = useMemo(() => {
    const groups = new Map<string, EventRecord[]>();
    for (const e of filtered) {
      const day = new Date(e.timestamp).toLocaleDateString(undefined, {
        weekday: "long",
        month: "short",
        day: "numeric",
      });
      const arr = groups.get(day) ?? [];
      arr.push(e);
      groups.set(day, arr);
    }
    return Array.from(groups.entries());
  }, [filtered]);

  return (
    <>
      <header className="mb-8">
        <div className="font-mono text-[10.5px] uppercase tracking-[0.24em] text-maroon-200/80">
          Timeline
        </div>
        <h1 className="mt-2 font-serif text-[44px] leading-tight text-cream-50">
          What happened.
        </h1>
      </header>

      <div className="mb-8 flex gap-2">
        <Chip active={tier === null} onClick={() => setTier(null)}>All</Chip>
        {[1, 2, 3, 4].map((t) => (
          <Chip key={t} active={tier === t} onClick={() => setTier(t)}>
            Tier {t}
          </Chip>
        ))}
      </div>

      {byDay.map(([day, items]) => (
        <section key={day} className="mb-10">
          <div className="mb-3 font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/70">
            {day}
          </div>
          <div className="grid gap-2">
            {items.map((e) => {
              const imgUrl = suspectFrameUrl(e);
              return (
                <Link
                  key={e.id}
                  href={`/timeline/${e.id}`}
                  className="card-glass ring-glow grid grid-cols-[80px_56px_1fr_auto] items-center gap-4 rounded-xl px-4 py-3 transition-transform hover:-translate-y-px"
                >
                  <span className="font-mono text-[12px] text-cream-50/55">
                    {new Date(e.timestamp).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                  {imgUrl ? (
                    <img
                      src={imgUrl}
                      alt={e.suspect_description ?? "Suspect frame"}
                      loading="lazy"
                      className="h-14 w-14 rounded-md object-cover ring-1 ring-maroon-300/20"
                      onError={(ev) => {
                        ev.currentTarget.style.display = "none";
                      }}
                    />
                  ) : (
                    <div className="h-14 w-14 rounded-md bg-maroon-300/10 ring-1 ring-maroon-300/15" />
                  )}
                  <div>
                    <div className="text-[14.5px] text-cream-50">
                      {e.one_line_summary}
                    </div>
                    <div className="mt-0.5 font-mono text-[11px] text-cream-50/50">
                      {e.scene} · {e.behavior_pattern}
                    </div>
                  </div>
                  <SeverityBadge tier={e.tier} />
                </Link>
              );
            })}
          </div>
        </section>
      ))}
    </>
  );
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-full px-4 py-1.5 text-[12px] font-medium transition-colors",
        active
          ? "bg-cream-50 text-maroon-900"
          : "border border-maroon-300/20 text-cream-50/75 hover:bg-maroon-300/10"
      )}
    >
      {children}
    </button>
  );
}
