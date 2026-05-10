"use client";
import { useEffect, useRef, useState } from "react";
import type { NodeSummary } from "@safewatch/api-types";
import type { LiveNode } from "@/lib/api";

type TileNode = NodeSummary | LiveNode;

// Per-node tone shift inside the maroon family - never green/amber.
// Tier shifts deepest near the porch (where the active incident lives).
const TONES: Record<string, { hot: string; cool: string }> = {
  node_porch: { hot: "#9A3142", cool: "#1F050A" },
  node_drive: { hot: "#7A1F2B", cool: "#120308" },
  node_back: { hot: "#5E1521", cool: "#1F050A" },
  node_garage: { hot: "#330810", cool: "#0A0103" },
};

/**
 * Layered render strategy:
 *   1. `useWebcam` (or auto-pick the first node) tries `getUserMedia` and
 *      pipes it into a `<video>`. This is the truthful "real camera" feed
 *      when the operator is on the same Mac as the brain.
 *   2. If the node has an MJPEG `stream_url` (mDNS-discovered LAN cam),
 *      we render it via `<img>` — Chrome/Safari handle the multipart frame
 *      reassembly natively.
 *   3. Otherwise we fall back to the original animated maroon canvas so
 *      the layout stays solid even with no source.
 */
export function CameraTile({
  node,
  height = 200,
  showHud = true,
  className,
  useWebcam = false,
}: {
  node: TileNode;
  height?: number;
  showHud?: boolean;
  className?: string;
  /** Render the operator's local webcam in this tile (Live page focus, etc.). */
  useWebcam?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [feed, setFeed] = useState<"webcam" | "mjpeg" | "synthetic">(
    "synthetic"
  );
  const [statusText, setStatusText] = useState<string>("");

  const liveStreamUrl = (node as LiveNode).stream_url;
  const registryStatus = (node as LiveNode).registry_status;

  // Webcam: only when explicitly requested. We don't ambush the user with
  // a permission prompt on the dashboard — the Live page opts in.
  useEffect(() => {
    if (!useWebcam) return;
    let cancelled = false;
    let stream: MediaStream | null = null;
    (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          setStatusText("webcam unsupported");
          return;
        }
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          await video.play().catch(() => {});
          setFeed("webcam");
        }
      } catch (e) {
        const msg =
          e && typeof e === "object" && "name" in e
            ? String((e as { name: string }).name)
            : "blocked";
        setStatusText(`webcam ${msg.toLowerCase()}`);
      }
    })();
    return () => {
      cancelled = true;
      if (stream) stream.getTracks().forEach((t) => t.stop());
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, [useWebcam]);

  // MJPEG fallback: only when not using the webcam and the node has a URL
  // we can reasonably display in an <img>. RTSP can't render in-browser
  // without a transcoder, so we leave that to the synthetic background.
  useEffect(() => {
    if (useWebcam) return;
    if (!liveStreamUrl) {
      setFeed("synthetic");
      return;
    }
    if (/^rtsp:/i.test(liveStreamUrl)) {
      setFeed("synthetic");
      setStatusText("rtsp · transcoder required");
      return;
    }
    setFeed("mjpeg");
  }, [useWebcam, liveStreamUrl]);

  // Synthetic background — only paints when we don't have a real feed.
  useEffect(() => {
    if (feed !== "synthetic") return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const tone = TONES[node.node_id] ?? TONES.node_porch!;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let raf = 0;

    const resize = () => {
      const r = canvas.getBoundingClientRect();
      canvas.width = r.width * dpr;
      canvas.height = r.height * dpr;
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    let t = 0;
    const draw = () => {
      const w = canvas.width;
      const h = canvas.height;
      const grad = ctx.createRadialGradient(
        w * 0.25,
        h * 0.3,
        0,
        w * 0.5,
        h * 0.6,
        Math.max(w, h) * 0.9
      );
      grad.addColorStop(0, tone.hot);
      grad.addColorStop(0.55, tone.cool);
      grad.addColorStop(1, "#0A0103");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, w, h);

      const haze = ctx.createLinearGradient(
        0,
        h * 0.5 + Math.sin(t * 0.008) * 30 * dpr,
        w,
        h * 0.5 + Math.cos(t * 0.006) * 30 * dpr
      );
      haze.addColorStop(0, "rgba(184,89,104,0.0)");
      haze.addColorStop(0.5, "rgba(184,89,104,0.10)");
      haze.addColorStop(1, "rgba(184,89,104,0.0)");
      ctx.fillStyle = haze;
      ctx.fillRect(0, 0, w, h);

      ctx.globalAlpha = 0.12;
      for (let i = 0; i < 600 * dpr; i++) {
        const x = Math.random() * w;
        const y = Math.random() * h;
        const v = Math.random();
        if (v > 0.85) ctx.fillStyle = "rgba(245,230,211,0.7)";
        else if (v > 0.5) ctx.fillStyle = "rgba(0,0,0,0.7)";
        else continue;
        ctx.fillRect(x, y, 1 * dpr, 1 * dpr);
      }
      ctx.globalAlpha = 1;

      const vg = ctx.createRadialGradient(
        w * 0.5,
        h * 0.5,
        Math.min(w, h) * 0.35,
        w * 0.5,
        h * 0.5,
        Math.max(w, h) * 0.7
      );
      vg.addColorStop(0, "rgba(0,0,0,0)");
      vg.addColorStop(1, "rgba(0,0,0,0.55)");
      ctx.fillStyle = vg;
      ctx.fillRect(0, 0, w, h);

      t++;
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [feed, node.node_id]);

  const time = new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  const recordingLabel =
    registryStatus === "warming"
      ? "● warming"
      : registryStatus === "crashed"
      ? "○ crashed"
      : node.online
      ? feed === "webcam"
        ? "● live · webcam"
        : feed === "mjpeg"
        ? "● live · lan"
        : "● rec"
      : "○ offline";

  return (
    <div
      className={
        "group relative overflow-hidden rounded-xl border border-maroon-300/10 bg-maroon-950 " +
        (className ?? "")
      }
      style={{ height }}
    >
      {feed === "webcam" && (
        <video
          ref={videoRef}
          muted
          playsInline
          autoPlay
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}
      {feed === "mjpeg" && liveStreamUrl && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={liveStreamUrl}
          alt={node.label}
          className="absolute inset-0 h-full w-full object-cover"
          onError={() => setFeed("synthetic")}
        />
      )}
      {feed === "synthetic" && (
        <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
      )}

      {/* scanline overlay - subtle */}
      <div className="pointer-events-none absolute inset-0 scanlines opacity-20 mix-blend-overlay" />

      {/* moving scan beam */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -inset-x-4 h-12 bg-gradient-to-b from-transparent via-maroon-200/8 to-transparent animate-scan" />
      </div>

      {showHud && (
        <>
          <div className="absolute top-3 left-3 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.18em] text-cream-50/85">
            <span
              className={
                "h-1.5 w-1.5 rounded-full " +
                (node.online
                  ? "bg-cream-50 shadow-[0_0_0_3px_rgba(245,230,211,0.18)] animate-pulse-soft"
                  : "bg-cream-50/30")
              }
            />
            {node.label}
          </div>
          <div className="absolute top-3 right-3 font-mono text-[10px] uppercase tracking-[0.22em] text-cream-50/65">
            {recordingLabel}
          </div>
          <div className="absolute bottom-3 left-3 right-3 flex items-end justify-between font-mono text-[10px] text-cream-50/60">
            <span className="uppercase tracking-[0.16em]">
              {node.scene ?? node.node_id}
              {statusText ? ` · ${statusText}` : ""}
            </span>
            <span>{time} · 24fps</span>
          </div>
        </>
      )}

      {/* hover lift */}
      <div className="pointer-events-none absolute inset-0 ring-0 ring-maroon-200/0 transition-all duration-300 group-hover:ring-1 group-hover:ring-maroon-200/40" />
    </div>
  );
}
