"use client";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CameraTile } from "@/components/CameraTile";
import { ReadyPillar } from "@/components/ReadyPillar";
import { cameraToNode, getNodes } from "@/lib/api";
import { useCameras } from "@/lib/liveStore";
import type { NodeSummary } from "@safewatch/api-types";

export default function LivePage() {
  const params = useSearchParams();
  const initial = params.get("node");
  const { cameras } = useCameras();
  const [fallback, setFallback] = useState<NodeSummary[]>([]);
  const [active, setActive] = useState<string | null>(initial);

  useEffect(() => {
    if (cameras.length > 0) return;
    getNodes().then(setFallback).catch(() => setFallback([]));
  }, [cameras.length]);

  const nodes: NodeSummary[] = useMemo(
    () => (cameras.length > 0 ? cameras.map(cameraToNode) : fallback),
    [cameras, fallback]
  );

  useEffect(() => {
    if (!active && nodes.length) setActive(nodes[0]!.node_id);
  }, [active, nodes]);

  const focus = nodes.find((n) => n.node_id === active);

  return (
    <>
      <header className="mb-6">
        <div className="font-mono text-[10.5px] uppercase tracking-[0.24em] text-maroon-200/80">
          Live mesh
        </div>
        <h1 className="mt-2 font-serif text-[44px] leading-tight text-cream-50">
          {focus?.label ?? "Live"}
        </h1>
        <p className="mt-2 max-w-[60ch] text-[14.5px] text-cream-50/65">
          {focus?.scene
            ? `Streaming from the ${focus.scene}. Frames stay on your device — the brain only sees structured event records.`
            : "Pick a node from the strip below."}
        </p>
        <div className="mt-4">
          <ReadyPillar variant="hero" />
        </div>
      </header>

      {focus && (
        <div className="relative overflow-hidden rounded-3xl border border-maroon-300/15 ring-glow">
          <CameraTile node={focus} height={560} useWebcam />
          <div className="absolute bottom-5 right-5 flex gap-2">
            <button className="rounded-full border border-cream-50/40 px-4 py-2 text-[12.5px] text-cream-50 hover:bg-cream-50/10">
              Snapshot
            </button>
            <button className="rounded-full bg-cream-50 px-4 py-2 text-[12.5px] font-medium text-maroon-900 hover:bg-cream-100">
              Talk through camera
            </button>
          </div>
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {nodes.map((n) => (
          <button
            key={n.node_id}
            onClick={() => setActive(n.node_id)}
            className={
              "block rounded-xl p-0 transition-all " +
              (active === n.node_id
                ? "ring-2 ring-maroon-200/70"
                : "ring-1 ring-maroon-300/10 hover:ring-maroon-200/40")
            }
          >
            <CameraTile node={n} height={120} />
          </button>
        ))}
      </div>
    </>
  );
}
