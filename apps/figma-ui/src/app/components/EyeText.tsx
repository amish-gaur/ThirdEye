import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";

/**
 * Render the actual letter "e" from the surrounding font, then place a small
 * almond eye accent ABOVE the letter (outline + black iris + red pupil that
 * tracks the cursor).
 */
function LetterEye() {
  const wrap = useRef<HTMLSpanElement>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const el = wrap.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height * 0.15;
      const dx = e.clientX - cx;
      const dy = e.clientY - cy;
      const dist = Math.min(1.6, Math.hypot(dx, dy) / 120);
      const ang = Math.atan2(dy, dx);
      setPos({ x: Math.cos(ang) * dist, y: Math.sin(ang) * dist });
    };
    window.addEventListener("mousemove", handler);
    return () => window.removeEventListener("mousemove", handler);
  }, []);

  return (
    <span ref={wrap} className="relative inline-block">
      <span style={{ position: "relative", zIndex: 0 }}>e</span>
      {/* eye sits inside the upper counter (the gap) of the e */}
      <span
        aria-hidden
        className="absolute pointer-events-none"
        style={{
          top: "0.43em",
          left: "0.13em",
          width: "0.30em",
          height: "0.19em",
          zIndex: 2,
        }}
      >
        <span
          className="block relative"
          style={{
            width: "100%",
            height: "100%",
            background: "#f4ead8",
            borderRadius: "50%",
            border: "0.04em solid currentColor",
            overflow: "hidden",
          }}
        >
          <motion.span
            className="block absolute"
            style={{
              width: "55%",
              height: "85%",
              background: "#c8222d",
              borderRadius: "50%",
              top: "8%",
              left: "22%",
            }}
            animate={{ x: pos.x * 4, y: pos.y * 2 }}
            transition={{ type: "spring", stiffness: 220, damping: 20 }}
          />
        </span>
      </span>
    </span>
  );
}

export function EyeText({
  children,
  className,
  style,
}: {
  children: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  const parts = children.split(/(e)/gi);
  return (
    <motion.span
      className={className}
      style={style}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.7 }}
    >
      {parts.map((p, i) =>
        p.toLowerCase() === "e" ? <LetterEye key={i} /> : <span key={i}>{p}</span>
      )}
    </motion.span>
  );
}
