import { useEffect, useRef, useState } from "react";
import { motion, useMotionValue, useSpring, useTransform } from "motion/react";
import { CameraRays } from "./CameraRays";

/**
 * Ceiling-mount dome security camera, drawn flat 2D (Incredibles vibe).
 * No gradients — color-block fills with offset shadow shapes for depth.
 * Single round black lens with a red dot that tracks the cursor.
 */
export function SecurityEye({ size = 360 }: { size?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const mx = useMotionValue(0);
  const my = useMotionValue(0);
  const sx = useSpring(mx, { stiffness: 110, damping: 16 });
  const sy = useSpring(my, { stiffness: 110, damping: 16 });

  const dotX = useTransform(sx, (v) => v * 22);
  const dotY = useTransform(sy, (v) => v * 22);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const el = ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      const dx = (e.clientX - cx) / (window.innerWidth / 2);
      const dy = (e.clientY - cy) / (window.innerHeight / 2);
      mx.set(Math.max(-1, Math.min(1, dx)));
      my.set(Math.max(-1, Math.min(1, dy)));
    };
    window.addEventListener("mousemove", handler);
    return () => window.removeEventListener("mousemove", handler);
  }, [mx, my]);

  const [rec, setRec] = useState(true);
  useEffect(() => {
    const id = setInterval(() => setRec((r) => !r), 900);
    return () => clearInterval(id);
  }, []);

  // Palette — cream Incredibles shell, glowy red interior
  const INK = "#1a0306";
  const SHELL = "#f4ead8";        // cream shell
  const SHELL_LIGHT = "#fff6e2";  // brighter top highlight
  const SHELL_SHADOW = "#c89a5e"; // warm tan undershadow
  const RING = "#1a1417";
  const LENS = "#0d0204";
  const RED = "#ff3146";
  const RED_HI = "#ffb070";

  const W = size;
  const H = size * 0.95;

  return (
    <div
      ref={ref}
      className="relative select-none"
      style={{ width: W, height: H }}
    >
      {/* RAYS — emanate from the red dot, sit behind everything */}
      <CameraRays />

      {/* SOFT FLOOR SHADOW under the camera */}
      <div
        className="absolute left-1/2 -translate-x-1/2 rounded-full"
        style={{
          bottom: -10,
          width: W * 0.7,
          height: 18,
          background: INK,
          opacity: 0.18,
          filter: "blur(6px)",
        }}
      />

      {/* CEILING PLATE (the round mount disk) */}
      <div
        className="absolute left-1/2 -translate-x-1/2"
        style={{ top: 0, width: W * 0.9, height: H * 0.16 }}
      >
        {/* shadow block under plate */}
        <div
          className="absolute rounded-[50%]"
          style={{
            inset: 0,
            top: 6,
            background: INK,
          }}
        />
        {/* plate */}
        <div
          className="absolute rounded-[50%]"
          style={{
            inset: 0,
            background: SHELL,
            border: `4px solid ${INK}`,
          }}
        />
        {/* plate top highlight (offset block, not gradient) */}
        <div
          className="absolute"
          style={{
            top: 6,
            left: "12%",
            right: "12%",
            height: 6,
            background: SHELL_LIGHT,
            borderRadius: 999,
          }}
        />
      </div>

      {/* DOME BODY — circular ceiling dome */}
      <div
        className="absolute left-1/2 -translate-x-1/2"
        style={{
          top: H * 0.10,
          width: W * 0.78,
          height: W * 0.78,
        }}
      >
        {/* drop-shadow block (flat, offset) */}
        <div
          className="absolute rounded-full"
          style={{
            inset: 0,
            transform: "translate(8px, 12px)",
            background: INK,
          }}
        />
        {/* dome shell */}
        <div
          className="absolute rounded-full"
          style={{
            inset: 0,
            background: SHELL,
            border: `5px solid ${INK}`,
          }}
        />
        {/* bottom shadow plate (smart shadow, flat color) */}
        <div
          className="absolute rounded-full overflow-hidden"
          style={{ inset: 5 }}
        >
          <div
            className="absolute"
            style={{
              left: 0,
              right: 0,
              bottom: 0,
              height: "55%",
              background: SHELL_SHADOW,
              clipPath: "ellipse(75% 100% at 50% 100%)",
            }}
          />
          {/* top highlight plate */}
          <div
            className="absolute"
            style={{
              top: "8%",
              left: "18%",
              width: "44%",
              height: "14%",
              background: SHELL_LIGHT,
              borderRadius: 999,
              transform: "rotate(-12deg)",
            }}
          />
        </div>

        {/* IR LED RING — small dots around the lens */}
        <div className="absolute inset-0">
          {Array.from({ length: 16 }).map((_, i) => {
            const a = (i / 16) * Math.PI * 2;
            const r = (W * 0.78) / 2 - 28;
            const x = Math.cos(a) * r;
            const y = Math.sin(a) * r;
            return (
              <div
                key={i}
                className="absolute top-1/2 left-1/2 rounded-full"
                style={{
                  width: 6,
                  height: 6,
                  background: "#5a1520",
                  border: `1.5px solid ${INK}`,
                  transform: `translate(${x - 3}px, ${y - 3}px)`,
                }}
              />
            );
          })}
        </div>

        {/* LENS HOUSING (dark inset) */}
        <div
          className="absolute top-1/2 left-1/2 rounded-full"
          style={{
            width: "52%",
            height: "52%",
            transform: "translate(-50%, -50%)",
            background: RING,
            border: `4px solid ${INK}`,
          }}
        >
          {/* the BLACK LENS */}
          <div
            className="absolute top-1/2 left-1/2 rounded-full overflow-hidden"
            style={{
              width: "82%",
              height: "82%",
              transform: "translate(-50%, -50%)",
              background: LENS,
              border: `3px solid ${INK}`,
            }}
          >
            {/* RED DOT — tracks cursor */}
            <motion.div
              className="absolute top-1/2 left-1/2 rounded-full"
              style={{
                width: "32%",
                height: "32%",
                x: dotX,
                y: dotY,
                translateX: "-50%",
                translateY: "-50%",
                background: RED,
                boxShadow: `0 0 18px ${RED_HI}, 0 0 32px ${RED}`,
              }}
            >
              {/* hot center */}
              <div
                className="absolute top-1/2 left-1/2 rounded-full"
                style={{
                  width: "45%",
                  height: "45%",
                  transform: "translate(-50%, -50%)",
                  background: RED_HI,
                }}
              />
            </motion.div>

            {/* glass crescent highlight (flat, not gradient) */}
            <div
              className="absolute"
              style={{
                top: "8%",
                left: "14%",
                width: "40%",
                height: "16%",
                background: "#3a2f33",
                borderRadius: 999,
                transform: "rotate(-18deg)",
                opacity: 0.85,
              }}
            />
          </div>
        </div>
      </div>

      {/* REC pill */}
      <div
        className="absolute left-1/2 -translate-x-1/2 flex items-center gap-2 px-3 py-1 rounded-full"
        style={{
          bottom: 4,
          background: INK,
          border: `2px solid ${INK}`,
          boxShadow: `0 3px 0 ${INK}`,
        }}
      >
        <span
          className="w-2 h-2 rounded-full"
          style={{
            background: rec ? RED_HI : "#3a0d14",
            boxShadow: rec ? `0 0 6px ${RED_HI}` : "none",
          }}
        />
        <span
          className="text-[10px] tracking-[0.3em]"
          style={{ fontFamily: "DM Mono, monospace", color: "#f4ead8" }}
        >
          REC · LIVE
        </span>
      </div>
    </div>
  );
}
