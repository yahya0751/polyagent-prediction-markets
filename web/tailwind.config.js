/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Terminal palette
        ink: {
          950: "#05070a",
          900: "#0a0d12",
          850: "#0d1117",
          800: "#11161d",
          700: "#161c25",
          600: "#1f2733",
          500: "#2a3340",
        },
        neon: {
          green: "#00ff9c",
          red: "#ff3355",
          yellow: "#ffd23f",
          purple: "#a855f7",
          cyan: "#22d3ee",
          blue: "#3b82f6",
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
        display: ['"Space Grotesk"', "system-ui", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 18px rgba(0,255,156,0.18), 0 0 60px rgba(0,255,156,0.06)",
        "glow-red": "0 0 18px rgba(255,51,85,0.22), 0 0 60px rgba(255,51,85,0.08)",
        "glow-purple": "0 0 18px rgba(168,85,247,0.20), 0 0 60px rgba(168,85,247,0.07)",
        inset: "inset 0 1px 0 rgba(255,255,255,0.04), inset 0 0 0 1px rgba(255,255,255,0.03)",
      },
      animation: {
        pulseSoft: "pulseSoft 2.4s ease-in-out infinite",
        scan: "scan 6s linear infinite",
        flicker: "flicker 4s steps(8,end) infinite",
      },
      keyframes: {
        pulseSoft: {
          "0%,100%": { opacity: 1 },
          "50%": { opacity: 0.55 },
        },
        scan: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100%)" },
        },
        flicker: {
          "0%,98%,100%": { opacity: 1 },
          "99%": { opacity: 0.85 },
        },
      },
    },
  },
  plugins: [],
};
