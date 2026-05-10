import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";

const INK = "#1a0306";
const CREAM = "#f4ead8";
const WINE = "#7a2230";
const RED = "#c8222d";
const GOLD = "#f4c97a";

/**
 * The iconic UC Davis water tower — cylindrical tank on a 4-leg lattice,
 * "UC DAVIS" wrapping the tank. Styled flat in the project's Incredibles palette.
 */
export function WaterTower({ size = 240 }: { size?: number }) {
  const W = size;
  const H = size * 1.55;
  const [moo, setMoo] = useState(false);

  const triggerMoo = () => {
    if (moo) return;
    setMoo(true);
    window.setTimeout(() => setMoo(false), 2400);
  };

  return (
    <div className="relative" style={{ width: W, height: H }}>
      <svg
        viewBox="0 0 240 372"
        width={W}
        height={H}
        style={{ display: "block", overflow: "visible" }}
      >
        {/* offset shadow for the whole structure */}
        <g transform="translate(5, 7)" opacity={0.85}>
          <Tower flat />
        </g>
        <Tower />

        {/* slow flag waving on top — clickable easter egg */}
        <motion.g
          style={{ transformOrigin: "120px 18px", cursor: "pointer" }}
          animate={{ rotate: [-3, 3, -3] }}
          transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
          onClick={triggerMoo}
          whileHover={{ scale: 1.08 }}
          whileTap={{ scale: 0.92 }}
        >
          <line x1="120" y1="0" x2="120" y2="20" stroke={INK} strokeWidth={3} />
          <path
            d="M 120 2 L 152 8 L 148 16 L 152 24 L 120 18 Z"
            fill={RED}
            stroke={INK}
            strokeWidth={2.5}
            strokeLinejoin="round"
          />
          {/* invisible bigger hit area */}
          <rect x="115" y="-2" width="44" height="30" fill="transparent" />
        </motion.g>

        {/* subtle drip pulse from tank */}
        <motion.circle
          cx={120}
          cy={108}
          r={3}
          fill={WINE}
          animate={{ cy: [108, 240], opacity: [0, 0.7, 0] }}
          transition={{ duration: 2.6, repeat: Infinity, ease: "easeIn", delay: 0.4 }}
        />
      </svg>

      {/* MOO POPUP */}
      <AnimatePresence>
        {moo && (
          <motion.div
            className="absolute pointer-events-none"
            style={{ left: "-30%", bottom: "-8%", width: "180%" }}
            initial={{ y: 80, opacity: 0, scale: 0.7 }}
            animate={{ y: 0, opacity: 1, scale: 1 }}
            exit={{ y: 60, opacity: 0, scale: 0.85 }}
            transition={{ type: "spring", stiffness: 240, damping: 18 }}
          >
            <div className="relative flex items-end justify-center">
              {/* speech bubble */}
              <motion.div
                className="absolute"
                style={{
                  right: "8%",
                  bottom: "78%",
                  background: CREAM,
                  border: `4px solid ${INK}`,
                  borderRadius: 16,
                  padding: "10px 18px",
                  boxShadow: `0 6px 0 ${INK}`,
                  fontFamily: "Playfair Display, serif",
                  fontWeight: 900,
                  fontSize: 28,
                  color: RED,
                  letterSpacing: "0.04em",
                  whiteSpace: "nowrap",
                }}
                animate={{ rotate: [-3, 3, -3] }}
                transition={{ duration: 0.5, repeat: Infinity }}
              >
                MOOOOO!!!!
                <span
                  style={{
                    position: "absolute",
                    bottom: -14,
                    left: 28,
                    width: 0,
                    height: 0,
                    borderLeft: "10px solid transparent",
                    borderRight: "10px solid transparent",
                    borderTop: `14px solid ${INK}`,
                  }}
                />
                <span
                  style={{
                    position: "absolute",
                    bottom: -8,
                    left: 32,
                    width: 0,
                    height: 0,
                    borderLeft: "6px solid transparent",
                    borderRight: "6px solid transparent",
                    borderTop: `10px solid ${CREAM}`,
                  }}
                />
              </motion.div>

              {/* the big cow */}
              <BigCow />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function BigCow() {
  const sw = 4;
  return (
    <svg viewBox="0 0 320 200" width="100%" style={{ display: "block", overflow: "visible" }}>
      {/* offset shadow */}
      <g transform="translate(4, 6)" opacity={0.9}>
        <ellipse cx="150" cy="130" rx="100" ry="42" fill={INK} />
        <circle cx="240" cy="100" r="38" fill={INK} />
      </g>

      {/* legs */}
      {[88, 124, 168, 200].map((x, i) => (
        <g key={i}>
          <rect x={x} y="148" width="18" height="42" fill={CREAM} stroke={INK} strokeWidth={sw} />
          <rect x={x - 1} y="186" width="20" height="8" fill={INK} />
        </g>
      ))}

      {/* body */}
      <ellipse cx="150" cy="124" rx="100" ry="42" fill={CREAM} stroke={INK} strokeWidth={sw} />

      {/* spots */}
      <ellipse cx="118" cy="112" rx="20" ry="13" fill={INK} />
      <ellipse cx="156" cy="138" rx="16" ry="9" fill={INK} />
      <ellipse cx="186" cy="108" rx="14" ry="9" fill={INK} />
      <ellipse cx="86" cy="128" rx="10" ry="6" fill={INK} />

      {/* tail */}
      <path
        d="M 56 116 Q 38 116 38 142 L 46 142 Q 46 124 60 126 Z"
        fill={CREAM}
        stroke={INK}
        strokeWidth={sw}
        strokeLinejoin="round"
      />
      <path d="M 36 138 L 46 152 L 38 156 Z" fill={INK} />

      {/* udder */}
      <ellipse cx="120" cy="156" rx="14" ry="10" fill={WINE} stroke={INK} strokeWidth={sw} />
      <circle cx="114" cy="166" r="2.5" fill={INK} />
      <circle cx="120" cy="167" r="2.5" fill={INK} />
      <circle cx="126" cy="166" r="2.5" fill={INK} />

      {/* head */}
      <circle cx="240" cy="100" r="38" fill={CREAM} stroke={INK} strokeWidth={sw} />
      {/* head spot */}
      <ellipse cx="226" cy="86" rx="10" ry="7" fill={INK} />

      {/* snout */}
      <ellipse cx="262" cy="116" rx="22" ry="16" fill={WINE} stroke={INK} strokeWidth={sw} />
      <ellipse cx="254" cy="116" rx="2.4" ry="3" fill={INK} />
      <ellipse cx="270" cy="116" rx="2.4" ry="3" fill={INK} />
      {/* mouth — open mooing */}
      <path
        d="M 252 124 Q 262 134 272 124"
        fill={INK}
        stroke={INK}
        strokeWidth={2}
        strokeLinejoin="round"
      />

      {/* eyes (squeezed shut from mooing) */}
      <path d="M 230 92 Q 236 86 242 92" fill="none" stroke={INK} strokeWidth={3} strokeLinecap="round" />
      <path d="M 250 92 Q 256 86 262 92" fill="none" stroke={INK} strokeWidth={3} strokeLinecap="round" />

      {/* ears */}
      <path
        d="M 214 82 Q 200 70 210 92 Z"
        fill={CREAM}
        stroke={INK}
        strokeWidth={sw}
        strokeLinejoin="round"
      />
      <path
        d="M 266 82 Q 280 70 270 92 Z"
        fill={CREAM}
        stroke={INK}
        strokeWidth={sw}
        strokeLinejoin="round"
      />

      {/* horns */}
      <path d="M 222 76 Q 218 64 228 70" fill={CREAM} stroke={INK} strokeWidth={sw} strokeLinejoin="round" />
      <path d="M 258 76 Q 262 64 252 70" fill={CREAM} stroke={INK} strokeWidth={sw} strokeLinejoin="round" />

      {/* gold collar tag */}
      <rect x="216" y="134" width="48" height="6" fill={INK} />
      <circle cx="240" cy="146" r="6" fill={GOLD} stroke={INK} strokeWidth={2.5} />
    </svg>
  );
}

function Tower({ flat = false }: { flat?: boolean }) {
  const tankFill = flat ? INK : CREAM;
  const legFill = flat ? INK : WINE;
  const cap = flat ? INK : GOLD;
  const sw = 3.5;

  return (
    <g>
      {/* TANK */}
      {/* tank body */}
      <rect x="48" y="40" width="144" height="76" rx="4" fill={tankFill} stroke={INK} strokeWidth={sw} />
      {/* top cap (rounded) */}
      <path d="M 48 44 Q 120 14 192 44 Z" fill={tankFill} stroke={INK} strokeWidth={sw} strokeLinejoin="round" />
      {/* finial */}
      <rect x="116" y="6" width="8" height="14" fill={cap} stroke={INK} strokeWidth={2.5} />
      <circle cx={120} cy={6} r={4} fill={cap} stroke={INK} strokeWidth={2.5} />
      {/* roof seam */}
      <line x1="48" y1="44" x2="192" y2="44" stroke={INK} strokeWidth={2} opacity={0.6} />
      {/* horizontal band rivets */}
      {!flat && (
        <>
          <line x1="48" y1="62" x2="192" y2="62" stroke={INK} strokeWidth={1.5} opacity={0.35} />
          <line x1="48" y1="100" x2="192" y2="100" stroke={INK} strokeWidth={1.5} opacity={0.35} />
        </>
      )}
      {/* accent band */}
      <rect x="48" y="68" width="144" height="22" fill={flat ? INK : WINE} />
      <line x1="48" y1="68" x2="192" y2="68" stroke={INK} strokeWidth={2} />
      <line x1="48" y1="90" x2="192" y2="90" stroke={INK} strokeWidth={2} />
      {/* bottom of tank — rounded base */}
      <path d="M 48 112 Q 120 132 192 112 Z" fill={tankFill} stroke={INK} strokeWidth={sw} strokeLinejoin="round" />

      {/* outlet pipe to legs */}
      <rect x="112" y="124" width="16" height="14" fill={legFill} stroke={INK} strokeWidth={2.5} />

      {/* LEGS — 4 splayed legs (drawn as 2 outer X-braced pairs) */}
      {/* outer legs */}
      <line x1="60" y1="126" x2="20" y2="328" stroke={legFill} strokeWidth={7} strokeLinecap="round" />
      <line x1="60" y1="126" x2="20" y2="328" stroke={INK} strokeWidth={9} strokeLinecap="round" opacity={0} />
      <line x1="180" y1="126" x2="220" y2="328" stroke={legFill} strokeWidth={7} strokeLinecap="round" />
      <line x1="60" y1="126" x2="20" y2="328" stroke={INK} strokeWidth={2.5} strokeLinecap="round" fill="none" opacity={0.0} />

      {/* leg outlines (dark stripes overlay) */}
      <path d="M 60 126 L 20 328" stroke={INK} strokeWidth={2.5} fill="none" />
      <path d="M 180 126 L 220 328" stroke={INK} strokeWidth={2.5} fill="none" />
      {/* inner legs (slightly narrower) */}
      <line x1="100" y1="130" x2="80" y2="328" stroke={legFill} strokeWidth={6} strokeLinecap="round" />
      <line x1="140" y1="130" x2="160" y2="328" stroke={legFill} strokeWidth={6} strokeLinecap="round" />
      <path d="M 100 130 L 80 328" stroke={INK} strokeWidth={2} fill="none" />
      <path d="M 140 130 L 160 328" stroke={INK} strokeWidth={2} fill="none" />

      {/* X-brace 1 (upper) */}
      <line x1="40" y1="200" x2="200" y2="200" stroke={legFill} strokeWidth={4} />
      <line x1="40" y1="200" x2="200" y2="200" stroke={INK} strokeWidth={2} />
      <line x1="40" y1="200" x2="200" y2="260" stroke={INK} strokeWidth={2} />
      <line x1="200" y1="200" x2="40" y2="260" stroke={INK} strokeWidth={2} />

      {/* X-brace 2 (mid) */}
      <line x1="32" y1="260" x2="208" y2="260" stroke={legFill} strokeWidth={4} />
      <line x1="32" y1="260" x2="208" y2="260" stroke={INK} strokeWidth={2} />
      <line x1="32" y1="260" x2="208" y2="310" stroke={INK} strokeWidth={2} />
      <line x1="208" y1="260" x2="32" y2="310" stroke={INK} strokeWidth={2} />

      {/* base ground beam */}
      <rect x="14" y="324" width="212" height="10" fill={legFill} stroke={INK} strokeWidth={sw} />
      {/* foot pads */}
      <rect x="8" y="334" width="28" height="10" fill={INK} />
      <rect x="68" y="334" width="28" height="10" fill={INK} />
      <rect x="144" y="334" width="28" height="10" fill={INK} />
      <rect x="204" y="334" width="28" height="10" fill={INK} />
    </g>
  );
}

