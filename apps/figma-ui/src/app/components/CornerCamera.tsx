import { useEffect, useRef } from "react";
import { motion, useMotionValue, useSpring, useTransform } from "motion/react";

/**
 * Wall-mount CCTV bullet camera that lives in the top-right of non-dashboard pages.
 * Drawn flat 2D (Incredibles vibe) with offset shadow blocks. The camera body
 * pans toward the cursor; a soft drop-shadow shifts opposite for parallax.
 */
export function CornerCamera({ size = 130 }: { size?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const mx = useMotionValue(0);
  const my = useMotionValue(0);
  const sx = useSpring(mx, { stiffness: 110, damping: 18 });
  const sy = useSpring(my, { stiffness: 110, damping: 18 });

  const rot = useTransform(sx, (v) => v * 16);
  const tilt = useTransform(sy, (v) => v * 6);
  const shadowX = useTransform(sx, (v) => -v * 10);
  const shadowY = useTransform(sy, (v) => -v * 6 + 10);
  const dotX = useTransform(sx, (v) => v * 4);
  const dotY = useTransform(sy, (v) => v * 4);

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

  const INK = "#1a0306";
  const SHELL = "#f4ead8";
  const SHELL_LIGHT = "#fff6e2";
  const SHELL_SHADOW = "#c89a5e";
  const LENS = "#0d0204";
  const RING = "#1a1417";
  const RED = "#ff3146";
  const RED_HI = "#ffb070";

  const W = size;
  const H = size * 0.95;

  return (
    <div
      ref={ref}
      className="absolute top-2 right-2 pointer-events-none"
      style={{ width: W, height: H, zIndex: 20 }}
    >
      {/* soft cursor-driven shadow */}
      <motion.div
        className="absolute"
        style={{
          inset: 0,
          background: INK,
          opacity: 0.18,
          filter: "blur(10px)",
          x: shadowX,
          y: shadowY,
          borderRadius: 24,
        }}
      />

      {/* wall plate (anchor) */}
      <div
        className="absolute"
        style={{
          top: 4,
          right: 6,
          width: 22,
          height: 22,
          background: SHELL,
          border: `3px solid ${INK}`,
          borderRadius: 6,
          boxShadow: `2px 3px 0 ${INK}`,
        }}
      >
        <div
          className="absolute rounded-full"
          style={{
            top: 6,
            left: 6,
            width: 6,
            height: 6,
            background: INK,
          }}
        />
      </div>

      {/* mount arm */}
      <div
        className="absolute"
        style={{
          top: 18,
          right: 22,
          width: 28,
          height: 8,
          background: SHELL_SHADOW,
          border: `3px solid ${INK}`,
          borderRadius: 4,
          transform: "rotate(-18deg)",
          transformOrigin: "right center",
        }}
      />

      {/* CAMERA BODY - pans with cursor */}
      <motion.div
        className="absolute"
        style={{
          top: 28,
          left: 4,
          width: W * 0.78,
          height: H * 0.5,
          rotate: rot,
          y: tilt,
          transformOrigin: "85% 50%",
        }}
      >
        {/* drop shadow block (flat) */}
        <div
          className="absolute"
          style={{
            inset: 0,
            transform: "translate(4px, 5px)",
            background: INK,
            borderRadius: 999,
          }}
        />
        {/* body */}
        <div
          className="absolute"
          style={{
            inset: 0,
            background: SHELL,
            border: `3px solid ${INK}`,
            borderRadius: 999,
            overflow: "hidden",
          }}
        >
          {/* under-shadow plate */}
          <div
            className="absolute"
            style={{
              left: 0,
              right: 0,
              bottom: 0,
              height: "48%",
              background: SHELL_SHADOW,
              clipPath: "ellipse(95% 100% at 50% 100%)",
            }}
          />
          {/* top highlight */}
          <div
            className="absolute"
            style={{
              top: "18%",
              left: "16%",
              width: "32%",
              height: "16%",
              background: SHELL_LIGHT,
              borderRadius: 999,
            }}
          />
          {/* sun-shade hood lip */}
          <div
            className="absolute"
            style={{
              left: -2,
              top: -2,
              bottom: -2,
              width: "22%",
              background: SHELL_SHADOW,
              border: `3px solid ${INK}`,
              borderRadius: 999,
            }}
          />
        </div>

        {/* LENS - flush with the front (left side) */}
        <div
          className="absolute"
          style={{
            left: -2,
            top: "50%",
            transform: "translateY(-50%)",
            width: H * 0.42,
            height: H * 0.42,
            background: RING,
            border: `3px solid ${INK}`,
            borderRadius: "50%",
          }}
        >
          <div
            className="absolute top-1/2 left-1/2 rounded-full overflow-hidden"
            style={{
              width: "78%",
              height: "78%",
              transform: "translate(-50%, -50%)",
              background: LENS,
              border: `2px solid ${INK}`,
            }}
          >
            <motion.div
              className="absolute top-1/2 left-1/2 rounded-full"
              style={{
                width: "36%",
                height: "36%",
                x: dotX,
                y: dotY,
                translateX: "-50%",
                translateY: "-50%",
                background: RED,
                boxShadow: `0 0 8px ${RED_HI}, 0 0 14px ${RED}`,
              }}
            >
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
          </div>
        </div>

        {/* tiny REC LED on top */}
        <div
          className="absolute rounded-full"
          style={{
            top: 4,
            right: "22%",
            width: 6,
            height: 6,
            background: RED,
            border: `1.5px solid ${INK}`,
          }}
        />
      </motion.div>
    </div>
  );
}
