import { motion } from "motion/react";
import { Video } from "lucide-react";

/**
 * Premium "awaiting live feed" empty state. A pulsing camera glyph inside
 * a soft circle, a slow scan bar that sweeps across the panel, a shimmer
 * pass on the ground, and an animated typing-dot caption.
 */
export function RobberWaiting({
  message = "waiting for live video",
  height = 220,
}: {
  message?: string;
  height?: number;
}) {
  const INK = "#1a0306";
  const CREAM = "#f4ead8";
  const SAND = "#efe1c2";
  const RED = "#c8222d";

  return (
    <div
      className="relative w-full overflow-hidden rounded-[12px] flex flex-col items-center justify-center gap-5"
      style={{
        background: SAND,
        border: `3px solid ${INK}`,
        height,
      }}
    >
      {/* slow horizontal scan bar */}
      <motion.div
        className="absolute inset-y-0 w-[40%] pointer-events-none"
        style={{
          background:
            "linear-gradient(90deg, transparent 0%, rgba(26,3,6,0.06) 50%, transparent 100%)",
        }}
        animate={{ x: ["-50%", "250%"] }}
        transition={{ duration: 4.2, repeat: Infinity, ease: "linear" }}
      />

      {/* camera glyph in pulsing rings */}
      <div className="relative flex items-center justify-center">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="absolute rounded-full"
            style={{
              width: 84,
              height: 84,
              border: `2px solid ${INK}`,
              opacity: 0.18,
            }}
            animate={{ scale: [1, 1.9], opacity: [0.22, 0] }}
            transition={{
              duration: 2.4,
              repeat: Infinity,
              delay: i * 0.8,
              ease: "easeOut",
            }}
          />
        ))}
        <div
          className="relative flex items-center justify-center rounded-full"
          style={{
            width: 64,
            height: 64,
            background: CREAM,
            border: `3px solid ${INK}`,
            boxShadow: `0 4px 0 ${INK}`,
          }}
        >
          <Video size={26} style={{ color: INK }} />
          <motion.span
            className="absolute rounded-full"
            style={{
              width: 8,
              height: 8,
              top: 10,
              right: 12,
              background: RED,
              boxShadow: `0 0 8px ${RED}`,
            }}
            animate={{ opacity: [1, 0.25, 1] }}
            transition={{ duration: 1.2, repeat: Infinity }}
          />
        </div>
      </div>

      {/* caption + animated dots */}
      <div className="flex items-baseline gap-1.5 z-10">
        <span
          style={{
            fontFamily: "Playfair Display, serif",
            fontWeight: 800,
            fontStyle: "italic",
            color: INK,
            fontSize: 18,
            letterSpacing: "-0.01em",
          }}
        >
          {message}
        </span>
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="rounded-full"
            style={{ width: 5, height: 5, background: INK, display: "inline-block" }}
            animate={{ opacity: [0.2, 1, 0.2], y: [0, -2, 0] }}
            transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.18 }}
          />
        ))}
      </div>

      {/* live signal bar at the bottom */}
      <div
        className="absolute left-6 right-6 bottom-3 h-1 rounded-full overflow-hidden"
        style={{ background: "rgba(26,3,6,0.12)" }}
      >
        <motion.div
          className="h-full"
          style={{ background: INK, width: "30%" }}
          animate={{ x: ["-100%", "330%"] }}
          transition={{ duration: 2.6, repeat: Infinity, ease: "easeInOut" }}
        />
      </div>

      {/* corner ID tag */}
      <div
        className="absolute top-3 left-4 flex items-center gap-2"
        style={{ fontFamily: "DM Mono, monospace", color: INK, opacity: 0.6 }}
      >
        <motion.span
          className="w-1.5 h-1.5 rounded-full"
          style={{ background: RED }}
          animate={{ opacity: [1, 0.2, 1] }}
          transition={{ duration: 1.4, repeat: Infinity }}
        />
        <span className="text-[10px] tracking-[0.25em]">SCANNING</span>
      </div>
      <div
        className="absolute top-3 right-4 text-[10px] tracking-[0.25em]"
        style={{ fontFamily: "DM Mono, monospace", color: INK, opacity: 0.5 }}
      >
        NO SIGNAL
      </div>
    </div>
  );
}
