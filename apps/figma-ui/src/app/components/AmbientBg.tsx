import { motion } from "motion/react";

/**
 * Subtle full-screen ambient layer (no rays — those live with the camera).
 * Slow drifting maroon wash + faint warm motes floating upward.
 */
export function AmbientBg() {
  return (
    <div
      className="fixed inset-0 pointer-events-none overflow-hidden"
      style={{ zIndex: 0 }}
    >
      <motion.div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at 20% 80%, rgba(122,34,48,0.10) 0%, rgba(122,34,48,0) 55%)",
          willChange: "transform",
        }}
        animate={{ x: [-30, 30, -30], y: [-10, 10, -10] }}
        transition={{ duration: 24, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at 80% 20%, rgba(244,201,122,0.08) 0%, rgba(244,201,122,0) 55%)",
          willChange: "transform",
        }}
        animate={{ x: [20, -20, 20], y: [10, -10, 10] }}
        transition={{ duration: 28, repeat: Infinity, ease: "easeInOut" }}
      />
      {Array.from({ length: 18 }).map((_, i) => {
        const left = (i * 53) % 100;
        const top = (i * 31) % 100;
        const dur = 18 + (i % 6) * 3;
        return (
          <motion.div
            key={i}
            className="absolute rounded-full"
            style={{
              left: `${left}%`,
              top: `${top}%`,
              width: 3,
              height: 3,
              background: "#7a2230",
              opacity: 0.25,
              willChange: "transform, opacity",
            }}
            animate={{ y: [0, -40, 0], opacity: [0, 0.35, 0] }}
            transition={{
              duration: dur,
              repeat: Infinity,
              ease: "easeInOut",
              delay: i * 0.4,
            }}
          />
        );
      })}
    </div>
  );
}
