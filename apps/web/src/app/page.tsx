"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, ShieldCheck, Radio } from "lucide-react";
import { CameraTile } from "@/components/CameraTile";
import { ReadyPillar } from "@/components/ReadyPillar";
import { SeverityBadge } from "@safewatch/ui/web";
import { Aurora } from "@/components/magic/Aurora";
import { Spotlight } from "@/components/magic/Spotlight";
import { ShimmerText } from "@/components/magic/ShimmerText";
import { cameraToNode, getEvents } from "@/lib/api";
import { useCameras, useIncidents } from "@/lib/liveStore";
import type { EventRecord, NodeSummary } from "@safewatch/api-types";

export default function Dashboard() {
  const { cameras } = useCameras();
  const { incidents } = useIncidents();
  const [history, setHistory] = useState<EventRecord[]>([]);

  // Backfill the timeline with whatever the legacy fixture endpoint
  // returns so a freshly opened dashboard isn't empty before the SSE
  // stream produces an event.
  useEffect(() => {
    getEvents()
      .then(setHistory)
      .catch(() => setHistory([]));
  }, []);

  const nodes: NodeSummary[] = useMemo(
    () =>
      cameras.length > 0
        ? cameras.map(cameraToNode)
        : history.length > 0
        ? Array.from(
            new Map(
              history.map((e) => [
                e.node_id,
                {
                  node_id: e.node_id,
                  label: e.scene || e.node_id,
                  online: true,
                  last_seen: e.timestamp,
                  scene: e.scene,
                } as NodeSummary,
              ])
            ).values()
          )
        : [],
    [cameras, history]
  );

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

  const active = events.find((e) => e.tier >= 3);

  return (
    <>
      {/* HERO */}
      <section className="relative overflow-hidden rounded-[28px] border border-maroon-300/10 bg-maroon-900/20 px-8 pt-12 pb-10 mb-8 ring-glow">
        <Aurora />
        <div className="relative z-[2]">
          <div className="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-[0.24em] text-maroon-200/80 animate-fade-up">
            <ShieldCheck className="h-3 w-3" />
            <span>Operator console · all systems local</span>
          </div>
          <h1 className="mt-4 max-w-[18ch] font-serif text-[58px] leading-[1.02] tracking-[-0.02em] text-cream-50 text-balance animate-fade-up">
            Everything calm <ShimmerText>at home</ShimmerText>.
          </h1>
          <p className="mt-5 max-w-[58ch] text-[15.5px] leading-relaxed text-cream-50/65 animate-fade-up">
            Four cameras streaming. Frames are analyzed in this browser, never
            uploaded. The brain only sees structured event records.
          </p>

          <div className="mt-8">
            <ReadyPillar variant="hero" />
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <HeroStat label="Cameras online" value={`${nodes.filter((n) => n.online).length} / ${nodes.length}`} />
            <HeroStat label="Live incidents" value={String(incidents.length)} />
            <HeroStat label="Events today" value={String(events.length)} />
            <HeroStat label="Frames uploaded" value="0" tone="strong" />
          </div>
        </div>
      </section>

      {active && <ActiveIncident event={active} />}

      {/* LIVE CAMERAS */}
      <section className="mt-10">
        <SectionHead
          eyebrow="Mesh"
          title="Live cameras"
          accessory={
            <Link
              href="/live"
              className="inline-flex items-center gap-1 rounded-full border border-maroon-300/20 px-3.5 py-1.5 text-[12px] text-cream-50/80 hover:bg-maroon-300/10"
            >
              Open mesh <ArrowUpRight className="h-3 w-3" />
            </Link>
          }
        />
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {nodes.map((n) => (
            <Link
              key={n.node_id}
              href={`/live?node=${n.node_id}`}
              className="block focus:outline-none focus:ring-2 focus:ring-maroon-200/40 rounded-xl"
            >
              <CameraTile node={n} height={200} />
            </Link>
          ))}
        </div>
      </section>

      {/* RECENT EVENTS */}
      <section className="mt-10">
        <SectionHead
          eyebrow="History"
          title="Recent events"
          accessory={
            <Link
              href="/timeline"
              className="inline-flex items-center gap-1 rounded-full border border-maroon-300/20 px-3.5 py-1.5 text-[12px] text-cream-50/80 hover:bg-maroon-300/10"
            >
              Full timeline <ArrowUpRight className="h-3 w-3" />
            </Link>
          }
        />
        <div className="mt-4 grid gap-2">
          {events.slice(0, 5).map((e) => (
            <EventRow key={e.id} event={e} />
          ))}
        </div>
      </section>
    </>
  );
}

function HeroStat({
  label,
  value,
  tone = "soft",
}: {
  label: string;
  value: string;
  tone?: "soft" | "strong";
}) {
  return (
    <div
      className={
        tone === "strong"
          ? "rounded-full border border-maroon-200/40 bg-maroon-200/10 px-4 py-1.5 font-mono text-[11px] uppercase tracking-[0.18em] text-cream-50"
          : "rounded-full border border-maroon-300/15 bg-maroon-900/40 px-4 py-1.5 font-mono text-[11px] uppercase tracking-[0.16em] text-cream-50/75"
      }
    >
      <span className="opacity-70">{label}</span>
      <span className="mx-2 opacity-30">·</span>
      <span className="font-semibold text-cream-50">{value}</span>
    </div>
  );
}

function SectionHead({
  eyebrow,
  title,
  accessory,
}: {
  eyebrow: string;
  title: string;
  accessory?: React.ReactNode;
}) {
  return (
    <div className="flex items-end justify-between">
      <div>
        <div className="font-mono text-[10.5px] uppercase tracking-[0.24em] text-maroon-200/70">
          {eyebrow}
        </div>
        <h2 className="mt-1 font-serif text-[28px] leading-tight text-cream-50">
          {title}
        </h2>
      </div>
      {accessory}
    </div>
  );
}

function ActiveIncident({ event }: { event: EventRecord }) {
  return (
    <Spotlight className="relative overflow-hidden rounded-[22px] border border-maroon-200/25 bg-gradient-to-br from-maroon-700/70 via-maroon-800/70 to-maroon-950/90 ring-glow">
      <div className="relative z-[2] grid gap-6 p-7 md:grid-cols-[1fr_auto] md:items-center">
        <div>
          <div className="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-100/80">
            <Radio className="h-3 w-3 animate-pulse-soft" />
            Active incident · just now
          </div>
          <h3 className="mt-3 font-serif text-[30px] leading-[1.15] text-cream-50 text-balance max-w-[36ch]">
            {event.one_line_summary}
          </h3>
          {event.suspect_description && (
            <p className="mt-3 max-w-[60ch] text-[14.5px] text-cream-50/70">
              {event.suspect_description}
            </p>
          )}
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <SeverityBadge tier={event.tier} />
            {event.actions_taken.map((a) => (
              <span
                key={a}
                className="rounded-md bg-maroon-200/10 px-2.5 py-1 font-mono text-[10.5px] uppercase tracking-[0.14em] text-cream-50/75"
              >
                {a.replace(/_/g, " ")}
              </span>
            ))}
          </div>
        </div>
        <div className="flex flex-col gap-2 md:items-end">
          <Link
            href={`/timeline/${event.id}`}
            className="rounded-full bg-cream-50 px-5 py-2.5 text-[14px] font-medium text-maroon-900 hover:bg-cream-100"
          >
            Open incident
          </Link>
          <button className="rounded-full border border-cream-50/70 px-5 py-2.5 text-[14px] font-medium text-cream-50 hover:bg-cream-50/10">
            Acknowledge
          </button>
        </div>
      </div>
    </Spotlight>
  );
}

function EventRow({ event }: { event: EventRecord }) {
  return (
    <Link
      href={`/timeline/${event.id}`}
      className="card-glass ring-glow group grid grid-cols-[64px_1fr_auto] items-center gap-4 rounded-xl px-4 py-3 transition-transform hover:-translate-y-px"
    >
      <div
        className="h-12 w-16 rounded-md"
        style={{
          background:
            "linear-gradient(135deg, #1F050A 0%, #5E1521 60%, #9A3142 100%)",
        }}
      />
      <div className="min-w-0">
        <div className="truncate text-[14.5px] text-cream-50">
          {event.one_line_summary}
        </div>
        <div className="mt-0.5 flex items-center gap-2 font-mono text-[11px] text-cream-50/55">
          <span>{new Date(event.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
          <span className="opacity-30">·</span>
          <span>{event.scene}</span>
          <span className="opacity-30">·</span>
          <span className="uppercase tracking-[0.14em]">{event.behavior_pattern}</span>
        </div>
      </div>
      <SeverityBadge tier={event.tier} />
    </Link>
  );
}
