import * as React from "react";

type Tier = 1 | 2 | 3 | 4;

const labels: Record<Tier, string> = {
  1: "Ambient",
  2: "Notice",
  3: "Alert",
  4: "Critical",
};

// Monochromatic — all shades within the maroon family.
const styles: Record<Tier, { bg: string; ring: string; dot: string; fg: string }> = {
  1: { bg: "rgba(201,138,147,0.14)", ring: "rgba(201,138,147,0.28)", dot: "#C98A93", fg: "#E5B4BB" },
  2: { bg: "rgba(154,49,66,0.18)", ring: "rgba(154,49,66,0.40)", dot: "#9A3142", fg: "#E5B4BB" },
  3: { bg: "rgba(94,21,33,0.45)", ring: "rgba(184,89,104,0.55)", dot: "#B85968", fg: "#F2D9DC" },
  4: { bg: "rgba(31,5,10,0.85)", ring: "rgba(184,89,104,0.85)", dot: "#E5B4BB", fg: "#FBF1E7" },
};

export function SeverityBadge({ tier }: { tier: Tier }) {
  const s = styles[tier];
  const pulse = tier === 4;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 10px",
        borderRadius: 999,
        background: s.bg,
        boxShadow: `inset 0 0 0 1px ${s.ring}`,
        color: s.fg,
        fontSize: 10.5,
        fontWeight: 600,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        fontFamily:
          '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace',
      }}
    >
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: 999,
          background: s.dot,
          boxShadow: `0 0 0 ${pulse ? 4 : 0}px rgba(229,180,187,0.18)`,
          animation: pulse ? "swp 1.4s ease-in-out infinite" : undefined,
        }}
      />
      Tier {tier} · {labels[tier]}
      <style>{`@keyframes swp{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.55;transform:scale(1.4)}}`}</style>
    </span>
  );
}
