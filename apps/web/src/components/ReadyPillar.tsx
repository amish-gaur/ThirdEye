"use client";

import { useLiveStore } from "@/lib/liveStore";

const warmupClasses = (state: string | undefined): { dot: string; label: string } => {
  if (state === "ready")
    return {
      dot: "bg-cream-50 shadow-[0_0_0_3px_rgba(245,230,211,0.18)]",
      label: "ready",
    };
  if (state === "warming")
    return { dot: "bg-maroon-200 animate-pulse-soft", label: "warming" };
  return { dot: "bg-cream-50/30", label: "cold" };
};

/**
 * Surface the action router's "READY" state — the web equivalent of the
 * iOS BackendStatus banner. Three layers in priority order:
 *   1. Backend reachable on `/health`?
 *   2. SSE incident stream connected?
 *   3. How many cameras are warming vs running vs crashed?
 *
 * The compact variant fits the nav; the wide variant lives at the top
 * of the dashboard so the operator can see at a glance whether the
 * vision pipeline is actually feeding the brain.
 */
export function ReadyPillar({ variant = "compact" }: { variant?: "compact" | "hero" }) {
  const { backend, cameras, streamState, health, warmup } = useLiveStore();
  const warm = warmupClasses(warmup?.state);

  const running = cameras.filter((c) => c.status === "running").length;
  const warming = cameras.filter((c) => c.status === "warming").length;
  const crashed = cameras.filter((c) => c.status === "crashed").length;

  const overall: "ready" | "warming" | "offline" =
    backend === "offline"
      ? "offline"
      : warming > 0 && running === 0
      ? "warming"
      : "ready";

  const label =
    overall === "ready"
      ? backend === "live"
        ? "ready"
        : "connecting"
      : overall === "warming"
      ? "warming"
      : "offline";

  const dot =
    overall === "ready"
      ? "bg-cream-50 shadow-[0_0_0_3px_rgba(245,230,211,0.18)] animate-pulse-soft"
      : overall === "warming"
      ? "bg-maroon-200 animate-pulse-soft"
      : "bg-cream-50/30";

  if (variant === "compact") {
    return (
      <span className="hidden sm:inline-flex items-center gap-1.5 rounded-full border border-maroon-300/15 bg-maroon-900/40 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.16em] text-maroon-100">
        <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
        {label} · {running}/{cameras.length || 0} live
        {streamState === "error" && (
          <span className="ml-1 text-cream-50/50">· stream retry</span>
        )}
      </span>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2 font-mono text-[10.5px] uppercase tracking-[0.18em]">
      <span
        className={
          overall === "ready"
            ? "rounded-full border border-maroon-200/40 bg-maroon-200/10 px-3 py-1 text-cream-50"
            : overall === "warming"
            ? "rounded-full border border-maroon-300/30 bg-maroon-900/40 px-3 py-1 text-cream-50/80"
            : "rounded-full border border-cream-50/20 bg-maroon-950/60 px-3 py-1 text-cream-50/55"
        }
      >
        <span className={`mr-2 inline-block h-1.5 w-1.5 rounded-full ${dot}`} />
        backend · {label}
      </span>
      <span className="rounded-full border border-maroon-300/15 bg-maroon-900/40 px-3 py-1 text-cream-50/75">
        cameras · {running} running · {warming} warming
        {crashed > 0 ? ` · ${crashed} crashed` : ""}
      </span>
      <span className="rounded-full border border-maroon-300/15 bg-maroon-900/40 px-3 py-1 text-cream-50/75">
        stream ·{" "}
        {streamState === "open"
          ? "subscribed"
          : streamState === "error"
          ? "retrying"
          : "connecting"}
      </span>
      <span className="rounded-full border border-maroon-300/15 bg-maroon-900/40 px-3 py-1 text-cream-50/75">
        <span className={`mr-2 inline-block h-1.5 w-1.5 rounded-full ${warm.dot}`} />
        models · {warm.label}
        {warmup && warmup.elapsed_s > 0 ? ` · ${warmup.elapsed_s.toFixed(1)}s` : ""}
      </span>
      {health?.public_base_url && (
        <span className="rounded-full border border-maroon-300/15 bg-maroon-900/40 px-3 py-1 text-cream-50/55">
          tunnel · {new URL(health.public_base_url).host}
        </span>
      )}
    </div>
  );
}
