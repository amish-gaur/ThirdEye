import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/**/*.{ts,tsx}",
    "../../packages/ui/src/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        cream: {
          50: "#FBF1E7",
          100: "#F5E6D3",
          200: "#E8D4BC",
          300: "#D4B896",
        },
        maroon: {
          50: "#F2D9DC",
          100: "#E5B4BB",
          200: "#C98A93",
          300: "#B85968",
          400: "#9A3142",
          500: "#7A1F2B",
          600: "#5E1521",
          700: "#4A0E18",
          800: "#330810",
          900: "#1F050A",
          950: "#120308",
        },
        ink: "#1F050A",
        // severity tints — all monochromatic in the maroon family
        sev: {
          1: "#C98A93", // ambient — the lightest, almost dust
          2: "#9A3142", // notice — mid maroon
          3: "#5E1521", // alert — deep
          4: "#1F050A", // critical — near black, with pulse
        },
      },
      fontFamily: {
        serif: ['"Newsreader"', '"Crimson Pro"', "Georgia", "serif"],
        mono: ['"JetBrains Mono"', '"SF Mono"', "ui-monospace", "monospace"],
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Inter",
          "system-ui",
          "sans-serif",
        ],
      },
      backgroundImage: {
        "aurora-maroon":
          "radial-gradient(circle at 20% 20%, rgba(184,89,104,0.30), transparent 50%), radial-gradient(circle at 80% 60%, rgba(74,14,24,0.45), transparent 55%), radial-gradient(circle at 50% 100%, rgba(154,49,66,0.35), transparent 60%)",
        "film-grain":
          "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)' opacity='0.5'/></svg>\")",
      },
      keyframes: {
        "aurora-shift": {
          "0%, 100%": { transform: "translate(0,0) scale(1)" },
          "50%": { transform: "translate(2%, -2%) scale(1.05)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.45" },
        },
        scan: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100%)" },
        },
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "aurora-shift": "aurora-shift 18s ease-in-out infinite",
        shimmer: "shimmer 3s linear infinite",
        "pulse-soft": "pulse-soft 2s ease-in-out infinite",
        scan: "scan 6s linear infinite",
        "fade-up": "fade-up 600ms ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
