import { motion } from "motion/react";

export type Tier = "ambient" | "notice" | "alert" | "emergency";

const TIER: Record<Tier, { label: string; bg: string; fg: string }> = {
  ambient: { label: "AMBIENT", bg: "#cfc4a6", fg: "#1a0306" },
  notice: { label: "NOTICE", bg: "#f4c97a", fg: "#1a0306" },
  alert: { label: "ALERT", bg: "#e85a3c", fg: "#fff5e1" },
  emergency: { label: "EMERGENCY", bg: "#c8222d", fg: "#fff5e1" },
};

export function IncidentRow({
  tier,
  title,
  node,
  time,
  delay = 0,
}: {
  tier: Tier;
  title: string;
  node: string;
  time: string;
  delay?: number;
}) {
  const t = TIER[tier];
  return (
    <motion.div
      initial={{ opacity: 0, x: -16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay, duration: 0.4 }}
      whileHover={{ x: 4 }}
      className="group relative flex items-center gap-4 px-5 py-4 cursor-pointer"
      style={{ borderBottom: "3px solid #1a0306" }}
    >
      <div
        className="w-10 h-10 rounded-full flex items-center justify-center"
        style={{
          background: t.bg,
          border: "3px solid #1a0306",
        }}
      >
        <motion.span
          className="w-2 h-2 rounded-full"
          style={{ background: t.fg }}
          animate={
            tier === "emergency" || tier === "alert"
              ? { scale: [1, 1.6, 1], opacity: [1, 0.4, 1] }
              : {}
          }
          transition={{ duration: 1.4, repeat: Infinity }}
        />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-3 mb-1">
          <span
            className="px-2 py-0.5 text-[10px] tracking-[0.2em]"
            style={{
              background: t.bg,
              color: t.fg,
              border: "2px solid #1a0306",
              fontFamily: "DM Mono, monospace",
            }}
          >
            {t.label}
          </span>
          <span
            className="text-[11px] text-[#5a1520]/80"
            style={{ fontFamily: "DM Mono, monospace" }}
          >
            {node}
          </span>
        </div>
        <div className="text-[#1a0306] text-[15px] truncate" style={{ fontFamily: "Playfair Display, serif" }}>
          {title}
        </div>
      </div>
      <div
        className="text-[12px] text-[#1a0306] tabular-nums"
        style={{ fontFamily: "DM Mono, monospace" }}
      >
        {time}
      </div>
    </motion.div>
  );
}
