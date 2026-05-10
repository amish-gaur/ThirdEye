"use client";
import { useEffect, useState } from "react";
import { Cpu, Lock, Zap, Activity } from "lucide-react";
import {
  ensureLoaded,
  embedText,
  subscribe,
  getEdgeState,
} from "@/lib/edgeInference";
import { Aurora } from "@/components/magic/Aurora";
import { Spotlight } from "@/components/magic/Spotlight";
import { ShimmerText } from "@/components/magic/ShimmerText";
import { NumberTicker } from "@/components/magic/NumberTicker";
import { BentoGrid, BentoCell } from "@/components/magic/BentoGrid";

export default function EdgeAdmin() {
  const [s, setS] = useState(getEdgeState());
  const [probe, setProbe] = useState("a person carrying a package");
  const [lastDims, setLastDims] = useState<number | null>(null);

  useEffect(() => subscribe(setS), []);
  useEffect(() => {
    ensureLoaded();
  }, []);

  const avgMs = s.inferenceCount ? s.totalMs / s.inferenceCount : 0;

  return (
    <>
      {/* HERO */}
      <section className="relative overflow-hidden rounded-[28px] border border-maroon-300/10 bg-maroon-900/20 px-8 pt-12 pb-10 mb-8 ring-glow">
        <Aurora />
        <div className="relative z-[2] max-w-[680px]">
          <div className="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-[0.24em] text-maroon-200/80">
            <Lock className="h-3 w-3" /> Edge inference
          </div>
          <h1 className="mt-4 font-serif text-[58px] leading-[1.02] tracking-[-0.02em] text-cream-50 text-balance">
            Frames never leave <ShimmerText>this device</ShimmerText>.
          </h1>
          <p className="mt-5 text-[15.5px] leading-relaxed text-cream-50/65">
            The vision and embedding models run inside this browser. The cloud
            sees structured event records — never pixels, never raw text. This
            page is the receipt.
          </p>
        </div>
      </section>

      {/* BENTO STATS */}
      <BentoGrid className="mb-6">
        <BentoCell span="2" className="row-span-2">
          <div className="relative flex h-full flex-col p-7">
            <div className="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/80">
              <Activity className="h-3 w-3" /> Privacy ledger
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <NumberTicker
                value={s.inferenceCount}
                className="font-serif text-[88px] leading-none text-cream-50"
              />
              <span className="font-mono text-[12px] uppercase tracking-[0.18em] text-maroon-200/70">
                inferences this session
              </span>
            </div>
            <div className="mt-auto grid grid-cols-2 gap-3 pt-6">
              <MiniStat label="Frames uploaded" value="0" foot="local-only" />
              <MiniStat
                label="Bytes uploaded"
                value="0"
                foot="for inference"
              />
            </div>
            <p className="mt-5 text-[13px] leading-relaxed text-cream-50/65">
              <span className="text-cream-50">What that means.</span>{" "}
              Your question (or a frame) is converted to a vector right here.
              Only the vector — never the raw input — leaves your device.
            </p>
          </div>
        </BentoCell>

        <BentoCell>
          <div className="flex h-full flex-col justify-between p-5">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/80 flex items-center gap-1.5">
              <Zap className="h-3 w-3" /> Avg latency
            </div>
            <div className="font-serif text-[44px] leading-none text-cream-50">
              {s.inferenceCount ? (
                <>
                  <NumberTicker value={Math.round(avgMs)} />
                  <span className="text-maroon-200/70 text-[20px] ml-1">ms</span>
                </>
              ) : (
                <span className="text-cream-50/30">—</span>
              )}
            </div>
            <div className="font-mono text-[11px] text-cream-50/50">
              CLIP text encoder
            </div>
          </div>
        </BentoCell>

        <BentoCell>
          <div className="flex h-full flex-col justify-between p-5">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/80 flex items-center gap-1.5">
              <Cpu className="h-3 w-3" /> Device
            </div>
            <div className="font-serif text-[28px] leading-tight text-cream-50">
              {s.device === "webgpu"
                ? "WebGPU"
                : s.device === "wasm"
                ? "WASM"
                : "Detecting…"}
            </div>
            <div className="font-mono text-[11px] text-cream-50/50">
              {s.device === "webgpu"
                ? "GPU-accelerated"
                : s.device === "wasm"
                ? "CPU fallback"
                : "negotiating"}
            </div>
          </div>
        </BentoCell>

        <BentoCell span="2">
          <div className="flex h-full flex-col p-5">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/80">
              Loaded model
            </div>
            <div className="mt-2 truncate font-mono text-[13px] text-cream-50">
              {s.modelId}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <KV k="task" v="feature-extraction" />
              <KV
                k="status"
                v={
                  <span
                    className={
                      s.status === "ready"
                        ? "text-cream-50"
                        : s.status === "error"
                        ? "text-maroon-100"
                        : "text-maroon-200"
                    }
                  >
                    ● {s.status}
                  </span>
                }
              />
              <KV
                k="loaded at"
                v={s.loadedAt ? new Date(s.loadedAt).toLocaleTimeString() : "—"}
              />
              <KV k="upload size" v="0 KB" />
            </div>
            <div className="mt-auto pt-4 flex gap-2">
              <button
                onClick={() => ensureLoaded()}
                className="rounded-full bg-cream-50 px-4 py-1.5 text-[12.5px] font-medium text-maroon-900 hover:bg-cream-100"
              >
                Warm up
              </button>
              <button
                onClick={async () => {
                  const v = await embedText(probe);
                  setLastDims(v.length);
                }}
                disabled={s.status !== "ready"}
                className="rounded-full border border-maroon-200/30 px-4 py-1.5 text-[12.5px] text-cream-50 disabled:opacity-40 hover:bg-maroon-200/10"
              >
                Run a probe
              </button>
            </div>
          </div>
        </BentoCell>
      </BentoGrid>

      {/* PROBE */}
      <Spotlight className="rounded-2xl card-glass ring-glow p-7">
        <div className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/80">
          Probe — see for yourself
        </div>
        <h3 className="mt-2 font-serif text-[24px] text-cream-50">
          Type anything. Watch the network tab stay empty.
        </h3>
        <div className="mt-5 flex gap-2">
          <input
            value={probe}
            onChange={(e) => setProbe(e.target.value)}
            className="flex-1 rounded-full border border-maroon-300/20 bg-maroon-950/60 px-5 py-3 font-serif text-[16px] text-cream-50 placeholder:text-cream-50/30 focus:border-maroon-200/50 focus:outline-none"
          />
          <button
            disabled={s.status !== "ready"}
            onClick={async () => {
              const v = await embedText(probe);
              setLastDims(v.length);
            }}
            className="rounded-full bg-cream-50 px-6 text-[14px] font-medium text-maroon-900 disabled:opacity-40 hover:bg-cream-100"
          >
            Embed
          </button>
        </div>
        {lastDims !== null && (
          <div className="mt-4 inline-flex items-center gap-2 rounded-md bg-maroon-200/10 px-3 py-2 font-mono text-[12px] text-cream-50/85">
            <span className="text-cream-50">✓</span>
            embedded into a {lastDims}-dimensional vector · 0 bytes uploaded · ran on{" "}
            <span className="text-cream-50">{s.device}</span>
          </div>
        )}
      </Spotlight>
    </>
  );
}

function MiniStat({
  label,
  value,
  foot,
}: {
  label: string;
  value: string;
  foot?: string;
}) {
  return (
    <div className="rounded-xl border border-maroon-300/15 bg-maroon-950/40 p-3">
      <div className="font-mono text-[9.5px] uppercase tracking-[0.22em] text-maroon-200/70">
        {label}
      </div>
      <div className="mt-1 font-serif text-[28px] leading-tight text-cream-50">
        {value}
      </div>
      {foot && (
        <div className="font-mono text-[10px] text-cream-50/45">{foot}</div>
      )}
    </div>
  );
}

function KV({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-maroon-300/10 py-1 font-mono text-[12px]">
      <span className="text-cream-50/45">{k}</span>
      <span className="truncate text-right text-cream-50/85">{v}</span>
    </div>
  );
}
