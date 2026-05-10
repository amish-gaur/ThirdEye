import type { CSSProperties } from "react";

type ThirdEyeLogoProps = {
  size?: number;
  /**
   * Color used for the eye sclera cutout so it reads against the ring.
   * Pass the surface behind the logo (e.g. cream brand pill).
   */
  bg?: string;
  className?: string;
  style?: CSSProperties;
};

/**
 * Third Eye mark: geometric “camera hand” — rounded square body, three
 * stepped fingers on top, circular lens on the left with an eye inside.
 * Single fill color via `currentColor`.
 */
export function ThirdEyeLogo({
  size = 28,
  bg = "transparent",
  className,
  style,
}: ThirdEyeLogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      xmlns="http://www.w3.org/2000/svg"
      fill="currentColor"
      role="img"
      aria-label="Third Eye"
      className={className}
      style={style}
    >
      {/* Lens ring (thick donut) on the left, overlaps the body */}
      <path
        d="M20 10 A16 16 0 1 1 20 54 A16 16 0 1 1 20 10 Z M20 17 A9 9 0 1 0 20 47 A9 9 0 1 0 20 17 Z"
        fillRule="evenodd"
      />

      {/* Main body: rounded square */}
      <rect x="27" y="28" width="33" height="30" rx="4.5" ry="4.5" />

      {/* Three fingers on top — height decreases left → right */}
      <rect x="29.5" y="9" width="7.5" height="19" rx="3.6" />
      <rect x="39" y="13" width="7" height="15" rx="3.4" />
      <rect x="48" y="17" width="6.5" height="11" rx="3.2" />

      {/* Eye inside lens */}
      <ellipse cx="20" cy="32" rx="7.2" ry="3.7" />
      <ellipse cx="20" cy="32" rx="5.4" ry="2.3" fill={bg} />
      <circle cx="20" cy="32" r="2.1" />
    </svg>
  );
}
