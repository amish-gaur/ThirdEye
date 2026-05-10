import { motion } from "motion/react";

/**
 * Red light rays fanning out from the camera's red dot. Meant to be placed
 * absolutely-positioned inside the SecurityEye container, anchored to the
 * lens center. Buttery smooth - long durations, GPU-friendly transforms.
 */
export function CameraRays() {
  const rays = Array.from({ length: 14 }).map((_, i) => ({
    angle: (i / 14) * 360,
    width: 80 + (i % 3) * 28,
    length: 1500,
    delay: i * 0.55,
    dur: 13 + (i % 4) * 2,
  }));

  return (
    <div
      className="absolute pointer-events-none"
      style={{
        left: "50%",
        top: "50%",
        width: 0,
        height: 0,
        zIndex: -1,
      }}
    >
      {/* warm red bloom at the source */}
      <motion.div
        className="absolute rounded-full"
        style={{
          width: 1100,
          height: 1100,
          marginLeft: -550,
          marginTop: -550,
          background:
            "radial-gradient(circle, rgba(220,40,55,0.25) 0%, rgba(220,40,55,0.08) 30%, rgba(220,40,55,0) 65%)",
          filter: "blur(24px)",
          willChange: "transform, opacity",
        }}
        animate={{ scale: [1, 1.08, 1], opacity: [0.85, 1, 0.85] }}
        transition={{ duration: 9, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* wide soft red rays */}
      {rays.map((r, i) => (
        <motion.div
          key={i}
          className="absolute origin-top"
          style={{
            top: 0,
            left: 0,
            width: r.width,
            height: r.length,
            marginLeft: -r.width / 2,
            transform: `rotate(${r.angle}deg)`,
            willChange: "transform, opacity",
          }}
          animate={{
            opacity: [0, 0.7, 0],
            rotate: [r.angle - 3, r.angle + 3, r.angle - 3],
          }}
          transition={{
            opacity: {
              duration: r.dur,
              repeat: Infinity,
              ease: "easeInOut",
              delay: r.delay,
            },
            rotate: {
              duration: r.dur * 1.6,
              repeat: Infinity,
              ease: "easeInOut",
              delay: r.delay,
            },
          }}
        >
          <div
            style={{
              width: "100%",
              height: "100%",
              background:
                "linear-gradient(180deg, rgba(220,40,55,0.55) 0%, rgba(200,34,45,0.18) 35%, rgba(122,34,48,0) 100%)",
              filter: "blur(16px)",
              clipPath: "polygon(48% 0%, 52% 0%, 90% 100%, 10% 100%)",
            }}
          />
        </motion.div>
      ))}

      {/* narrow sharper hot rays */}
      {Array.from({ length: 8 }).map((_, i) => {
        const angle = (i / 8) * 360 + 12;
        return (
          <motion.div
            key={`hot-${i}`}
            className="absolute origin-top"
            style={{
              top: 0,
              left: 0,
              width: 22,
              height: 1700,
              marginLeft: -11,
              transform: `rotate(${angle}deg)`,
              willChange: "transform, opacity",
            }}
            animate={{ opacity: [0, 0.6, 0] }}
            transition={{
              duration: 10 + i,
              repeat: Infinity,
              ease: "easeInOut",
              delay: i * 1.3,
            }}
          >
            <div
              style={{
                width: "100%",
                height: "100%",
                background:
                  "linear-gradient(180deg, rgba(255,90,80,0.7) 0%, rgba(220,40,55,0.18) 50%, rgba(122,34,48,0) 100%)",
                filter: "blur(6px)",
                clipPath: "polygon(40% 0%, 60% 0%, 88% 100%, 12% 100%)",
              }}
            />
          </motion.div>
        );
      })}
    </div>
  );
}
