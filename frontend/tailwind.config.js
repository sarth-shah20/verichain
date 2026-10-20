/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      colors: {
        // Pipeline 1 — Authenticity & Forensics
        pipeline1: {
          DEFAULT: "#0d9488", // teal-600
          soft: "#ccfbf1",
          softdark: "#134e4a",
        },
        // Pipeline 2 — Content Extraction & Validation
        pipeline2: {
          DEFAULT: "#4f46e5", // indigo-600
          soft: "#e0e7ff",
          softdark: "#312e81",
        },
        // Risk scale
        risk: {
          low: "#16a34a", // green-600
          mid: "#d97706", // amber-600
          high: "#dc2626", // red-600
        },
        brand: {
          DEFAULT: "#0d9488",
        },
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(0 0 0 / 0.04), 0 4px 12px -2px rgb(0 0 0 / 0.06)",
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "slide-in": {
          "0%": { opacity: "0", transform: "translateX(12px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "score-in": {
          "0%": { opacity: "0", transform: "scale(0.96)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.25s ease-out",
        "slide-in": "slide-in 0.2s ease-out",
        "score-in": "score-in 0.5s ease-out",
      },
    },
  },
  plugins: [],
};
