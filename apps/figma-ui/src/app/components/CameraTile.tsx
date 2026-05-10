import { motion } from "motion/react";
import { RobberWaiting } from "./RobberWaiting";

/**
 * Camera tile in an "awaiting backend feed" state. No fake video — just the
 * node identity, status, and a calm placeholder. Backend will mount the real
 * stream into the .feed-mount slot when wired up.
 */
export function CameraTile({
  name,
  status = "idle",
  delay = 0,
  large = false,
  streamUrl,
}: {
  name: string;
  status?: "live" | "idle" | "alert";
  delay?: number;
  large?: boolean;
  streamUrl?: string;
}) {
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

        {/* feed mount — MJPEG renders natively in <img> when streamUrl is set */}
        <div className="flex-1 relative" data-feed-mount={name}>
          {streamUrl ? (
            <img
              src={streamUrl}
              alt={name}
              className="absolute inset-0 w-full h-full object-cover"
              style={{ background: INK }}
            />
          ) : (
            <RobberWaiting height={large ? 280 : 180} />
          )}
        </div>
      </div>
    </motion.div>
  );
}
