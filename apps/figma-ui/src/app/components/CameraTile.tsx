import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { RobberWaiting } from "./RobberWaiting";

/**
 * Camera tile. Render priority:
 *   1. Browser webcam via getUserMedia (when `useWebcam` is set — typically
 *      the focused Live tile on the operator's own laptop).
 *   2. MJPEG `streamUrl` (LAN cam from the registry — phone, IP cam, etc).
 *   3. RobberWaiting placeholder (no source yet).
 *
 * RTSP can't render in a `<img>`, so any rtsp:// URL falls through to the
 * placeholder with a small note instead of silently breaking.
 */
export function CameraTile({
  name,
  status = "idle",
  delay = 0,
  large = false,
  streamUrl,
  useWebcam = false,
  previewUrl,
}: {
  name: string;
  status?: "live" | "idle" | "alert";
  delay?: number;
  large?: boolean;
  streamUrl?: string;
  useWebcam?: boolean;
  /**
   * Polling URL for the engine's annotated preview JPEG (the same image the
   * `ThirdEye Vision Engine` window draws — bounding boxes + confidences).
   * Cache-busted via a tick so the browser doesn't show a stale frame.
   */
  previewUrl?: string;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [webcamError, setWebcamError] = useState<string | null>(null);
  const [webcamReady, setWebcamReady] = useState(false);
  const [previewTick, setPreviewTick] = useState(0);

  // Refresh the polled preview at ~8 fps to match the engine's write cadence.
  useEffect(() => {
    if (!previewUrl) return;
    const id = window.setInterval(() => setPreviewTick((t) => t + 1), 125);
    return () => window.clearInterval(id);
  }, [previewUrl]);

  useEffect(() => {
    if (!useWebcam) return;
    let cancelled = false;
    let stream: MediaStream | null = null;
    (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          setWebcamError("not supported");
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
        const v = videoRef.current;
        if (v) {
          v.srcObject = stream;
          await v.play().catch(() => {});
          setWebcamReady(true);
        }
      } catch (e) {
        const msg =
          e && typeof e === "object" && "name" in e
            ? String((e as { name: string }).name).toLowerCase()
            : "blocked";
        setWebcamError(msg);
      }
    })();
    return () => {
      cancelled = true;
      if (stream) stream.getTracks().forEach((t) => t.stop());
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, [useWebcam]);

  const isRtsp = !!streamUrl && /^rtsp:/i.test(streamUrl);
  // Preview takes priority — it's the engine's truth (boxes + confidences).
  const showPreview = !!previewUrl;
  const showWebcam = !showPreview && useWebcam && webcamReady && !webcamError;
  const showMjpeg = !showPreview && !showWebcam && !!streamUrl && !isRtsp;
  const INK = "#1a0306";
  const CREAM = "#f4ead8";
  const SAND = "#e6d2a8";
  const RED = "#c8222d";
  const ORANGE = "#e85a3c";

  const dot =
    status === "alert" ? RED : status === "live" ? ORANGE : "#7a6a55";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.45 }}
      whileHover={{ y: -2 }}
      className={`relative ${large ? "aspect-video" : "aspect-[4/3]"}`}
    >
      {/* shadow block */}
      <div
        className="absolute inset-0 rounded-[14px]"
        style={{ background: INK, transform: "translate(6px, 8px)" }}
      />
      <div
        className="relative w-full h-full rounded-[14px] overflow-hidden flex flex-col"
        style={{
          background: SAND,
          border: `4px solid ${INK}`,
        }}
      >
        {/* header strip */}
        <div
          className="flex items-center justify-between px-3 py-2"
          style={{ background: CREAM, borderBottom: `3px solid ${INK}` }}
        >
          <div className="flex items-center gap-2">
            <motion.span
              className="w-2 h-2 rounded-full"
              style={{ background: dot }}
              animate={{ opacity: [1, 0.3, 1] }}
              transition={{ duration: 1.4, repeat: Infinity }}
            />
            <span
              className="text-[10px] tracking-[0.2em]"
              style={{ fontFamily: "DM Mono, monospace", color: INK }}
            >
              {name}
            </span>
          </div>
          <span
            className="text-[10px] px-2 py-0.5 tracking-[0.2em]"
            style={{
              fontFamily: "DM Mono, monospace",
              background: status === "alert" ? RED : INK,
              color: CREAM,
            }}
          >
            {status === "alert" ? "ALERT" : status === "live" ? "LIVE" : "IDLE"}
          </span>
        </div>

        {/* feed mount - engine preview (boxes) > webcam > MJPEG > placeholder */}
        <div className="flex-1 relative" data-feed-mount={name}>
          {showPreview && (
            <img
              src={`${previewUrl}?t=${previewTick}`}
              alt={name}
              className="absolute inset-0 w-full h-full object-cover"
              style={{ background: INK }}
              onError={(e) => {
                // 404 (engine not running yet) is fine — keep the existing
                // image visible until the next tick lands.
                (e.currentTarget as HTMLImageElement).style.opacity = "0.5";
              }}
              onLoad={(e) => {
                (e.currentTarget as HTMLImageElement).style.opacity = "1";
              }}
            />
          )}
          {useWebcam && !showPreview && (
            <video
              ref={videoRef}
              muted
              playsInline
              autoPlay
              className="absolute inset-0 w-full h-full object-cover"
              style={{ background: INK, display: showWebcam ? "block" : "none" }}
            />
          )}
          {showMjpeg && (
            <img
              src={streamUrl}
              alt={name}
              className="absolute inset-0 w-full h-full object-cover"
              style={{ background: INK }}
            />
          )}
          {!showPreview && !showWebcam && !showMjpeg && (
            <RobberWaiting height={large ? 280 : 180} />
          )}
          {(webcamError || isRtsp) && (
            <div
              className="absolute bottom-2 left-2 right-2 px-2 py-1 text-[9px] tracking-[0.18em] rounded"
              style={{
                fontFamily: "DM Mono, monospace",
                background: "rgba(26,3,6,0.85)",
                color: CREAM,
              }}
            >
              {webcamError ? `WEBCAM ${webcamError.toUpperCase()}` : "RTSP · TRANSCODER REQUIRED"}
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}
