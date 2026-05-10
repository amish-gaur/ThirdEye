import { motion, AnimatePresence } from "motion/react";
import { useEffect, useState } from "react";

/** A tiny "robber" sneaks across the screen while the security eye watches. */
export function RobberLoader({ onDone }: { onDone: () => void }) {
  const [phase, setPhase] = useState(0);
  const lines = [
    "INITIALIZING NODES",
    "SYNCING EDGE INFERENCE",
    "CALIBRATING THIRD EYE",
    "ALL SYSTEMS LOCAL",
  ];

  useEffect(() => {
    const id = setInterval(() => setPhase((p) => p + 1), 700);
    const finish = setTimeout(onDone, 3200);
    return () => {
      clearInterval(id);
      clearTimeout(finish);
    };
  }, [onDone]);

  return (
    <motion.div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center"
      style={{ background: "#1a0306" }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.5 }}
    >
      {/* scanlines */}
      <div
        className="absolute inset-0 opacity-20 pointer-events-none"
        style={{
          backgroundImage:
            "repeating-linear-gradient(0deg, rgba(255,200,200,0.05) 0 1px, transparent 1px 3px)",
        }}
      />

      {/* moonlit ground */}
      <div className="relative w-[520px] h-[180px] overflow-hidden border-y border-[#7a2230]/40">
        {/* fence silhouette */}
        <div className="absolute bottom-0 left-0 right-0 h-10 bg-[#0d0204]" />
        {Array.from({ length: 26 }).map((_, i) => (
          <div
            key={i}
            className="absolute bottom-0 w-2 h-14 bg-[#0d0204]"
            style={{ left: `${i * 22}px` }}
          />
        ))}

        {/* spotlight sweep */}
        <motion.div
          className="absolute -top-10 left-0 w-[180px] h-[260px] origin-top"
          style={{
            background:
              "conic-gradient(from 200deg at 50% 0%, rgba(241,200,165,0.0) 0deg, rgba(241,200,165,0.18) 20deg, rgba(241,200,165,0.0) 40deg)",
          }}
          animate={{ x: [0, 380, 0] }}
          transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
        />

        {/* robber */}
        <motion.div
          className="absolute bottom-10"
          initial={{ x: -60 }}
          animate={{ x: 540 }}
          transition={{ duration: 3.2, ease: "linear" }}
        >
          <Robber />
        </motion.div>

        {/* loot bag $ flash */}
      </div>

      <div className="mt-10 w-[420px]">
        <div className="h-1 w-full bg-[#2a0608] overflow-hidden rounded-full">
          <motion.div
            className="h-full bg-gradient-to-r from-[#7a1521] via-[#c8333f] to-[#f1c8a5]"
            initial={{ width: 0 }}
            animate={{ width: "100%" }}
            transition={{ duration: 3, ease: "easeInOut" }}
          />
        </div>
        <div
          className="mt-3 text-[11px] tracking-[0.3em] text-[#f1c8a5]/70 text-center h-4"
          style={{ fontFamily: "DM Mono, monospace" }}
        >
          <AnimatePresence mode="wait">
            <motion.span
              key={phase}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
            >
              {lines[Math.min(phase, lines.length - 1)]}
            </motion.span>
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
}

function Robber() {
  return (
    <motion.svg
      width="56"
      height="68"
      viewBox="0 0 56 68"
      animate={{ y: [0, -2, 0] }}
      transition={{ duration: 0.4, repeat: Infinity }}
    >
      {/* body */}
      <ellipse cx="28" cy="44" rx="14" ry="18" fill="#0d0204" />
      {/* head */}
      <circle cx="28" cy="20" r="11" fill="#0d0204" />
      {/* mask band */}
      <rect x="16" y="16" width="24" height="6" fill="#2a0608" />
      {/* eyes */}
      <circle cx="23" cy="19" r="1.6" fill="#f1c8a5" />
      <circle cx="33" cy="19" r="1.6" fill="#f1c8a5" />
      {/* loot bag */}
      <motion.g
        animate={{ rotate: [-6, 6, -6] }}
        transition={{ duration: 0.6, repeat: Infinity }}
        style={{ transformOrigin: "44px 44px" }}
      >
        <circle cx="44" cy="46" r="9" fill="#7a1521" stroke="#f1c8a5" strokeWidth="1" />
        <text
          x="44"
          y="50"
          textAnchor="middle"
          fontSize="10"
          fill="#f1c8a5"
          fontFamily="serif"
        >
          $
        </text>
      </motion.g>
      {/* legs */}
      <motion.rect
        x="22"
        y="58"
        width="4"
        height="10"
        fill="#0d0204"
        animate={{ y: [58, 56, 58] }}
        transition={{ duration: 0.3, repeat: Infinity }}
      />
      <motion.rect
        x="30"
        y="58"
        width="4"
        height="10"
        fill="#0d0204"
        animate={{ y: [56, 58, 56] }}
        transition={{ duration: 0.3, repeat: Infinity }}
      />
    </motion.svg>
  );
}
