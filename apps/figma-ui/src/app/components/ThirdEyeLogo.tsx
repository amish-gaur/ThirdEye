import type { CSSProperties } from "react";

type ThirdEyeLogoProps = {
  size?: number;
  /** Sclera + lens flare cutouts (match the surface behind the icon). */
  bg?: string;
  className?: string;
  style?: CSSProperties;
};

/**
 * Third Eye — simplified flat OK-hand + eye (matches the bronze/maroon 3D
 * reference: thumb & index form the ring, three fingers up, eye in the O).
 * Angular finger shapes read “low poly” at small sizes; single fill via `currentColor`.
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
      {/* Palm / wrist — slight chamfer for a geometric silhouette */}
      <path d="M 21 40 L 56 40 L 58 42 L 58 54 L 56 58 L 22 58 L 18 54 L 18 44 L 21 40 Z" />

      {/* Three raised fingers — faceted trapezoids, slight outward spread */}
      <path d="M 31 40 L 39 40 L 41.5 7 L 33 5.5 Z" />
      <path d="M 39 40 L 46 40 L 48.5 11 L 42 10 Z" />
      <path d="M 46 40 L 54 40 L 56.5 15 L 50.5 14 Z" />

      {/* Thumb + index: circular aperture (even-odd hole) */}
      <path
        d="M 19 18 A14 14 0 1 1 19 46 A14 14 0 1 1 19 18 Z M 19 26 A6 6 0 1 0 19 38 A6 6 0 1 0 19 26 Z"
        fillRule="evenodd"
      />

      {/* Eye centered in the OK ring: lid ring + sclera + pupil + highlight */}
      <ellipse cx="19" cy="32" rx="6.8" ry="3.6" />
      <ellipse cx="19" cy="32" rx="5.1" ry="2.35" fill={bg} />
      <circle cx="19" cy="32" r="2.15" />
      <circle cx="20.6" cy="30.9" r="0.85" fill={bg} />
    </svg>
  );
}
