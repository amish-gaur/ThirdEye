import type { CSSProperties } from "react";

type ThirdEyeLogoProps = {
  size?: number;
  /**
   * Color shown through the inside of the OK ring + the eye sclera.
   * Pass the surface color the logo sits on (e.g. the cream brand pill)
   * so the cutout reads cleanly. Defaults to "transparent" so the logo
   * can sit on any surface; override when the surface has a known color.
   */
  bg?: string;
  className?: string;
  style?: CSSProperties;
};

/**
 * Third Eye / SafeWatch wordmark logo.
 *
 * A flat, single-color hand making the OK gesture with an eye nested
 * inside the thumb-and-index circle. Drawn in `currentColor` so the
 * caller controls the ink shade via `style={{ color }}` or className,
 * matching the rest of the Incredibles palette in the dashboard.
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
      {/* Three extended fingers (middle, ring, pinky), tilted slightly */}
      <rect x="32" y="3" width="6" height="22" rx="2.8" transform="rotate(8 35 14)" />
      <rect x="40" y="6" width="5.6" height="19" rx="2.6" transform="rotate(8 42.8 15.5)" />
      <rect x="47" y="10" width="5" height="15" rx="2.4" transform="rotate(8 49.5 17.5)" />

      {/* Palm + wrist that the fingers root into and the OK ring connects to */}
      <path d="M28 24 H54 a4 4 0 0 1 4 4 V54 a4 4 0 0 1 -4 4 H32 a4 4 0 0 1 -4 -4 Z" />

      {/* OK ring: outer circle with inner cutout (true donut via even-odd) */}
      <path
        d="M19 22 A14 14 0 1 1 19 50 A14 14 0 1 1 19 22 Z M19 28 A8 8 0 1 0 19 44 A8 8 0 1 0 19 28 Z"
        fillRule="evenodd"
      />

      {/* Eye nested in the OK: maroon almond outline, cutout sclera, maroon pupil */}
      <ellipse cx="19" cy="36" rx="6.5" ry="3.4" />
      <ellipse cx="19" cy="36" rx="5" ry="2.1" fill={bg} />
      <circle cx="19" cy="36" r="1.7" />
    </svg>
  );
}
