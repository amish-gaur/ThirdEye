export const color = {
  maroon: {
    900: "#4A0E18",
    700: "#7A1F2B",
    500: "#B85968",
  },
  cream: {
    50: "#FAF0E6",
    100: "#F5E6D3",
    200: "#E8D4BC",
  },
  ink: "#2A1A1F",
  severity: {
    1: "#4A6741",
    2: "#C4843A",
    3: "#B33A3A",
    4: "#B33A3A",
  },
} as const;

export const font = {
  serif:
    '"Newsreader", "Crimson Pro", "Iowan Old Style", Georgia, "Times New Roman", serif',
  mono:
    '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, Consolas, monospace',
  sans:
    '-apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Helvetica, Arial, sans-serif',
} as const;

export const radius = {
  sm: "4px",
  md: "8px",
  lg: "14px",
  xl: "22px",
  pill: "999px",
} as const;

export const space = {
  1: "4px",
  2: "8px",
  3: "12px",
  4: "16px",
  5: "20px",
  6: "24px",
  8: "32px",
  10: "40px",
  12: "48px",
  16: "64px",
} as const;

export const shadow = {
  card: "0 1px 2px rgba(74, 14, 24, 0.06), 0 6px 18px rgba(74, 14, 24, 0.08)",
  modal: "0 24px 60px rgba(74, 14, 24, 0.18)",
} as const;

export const tokens = { color, font, radius, space, shadow } as const;
export type Tokens = typeof tokens;
