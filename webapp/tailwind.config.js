/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "var(--bg)",
        panel: "var(--bg-elev)",
        panel2: "var(--bg-elev-2)",
        line: "var(--line)",
        mute: "var(--muted)",
        gain: "var(--gain)",
        loss: "var(--loss)",
        amber: "var(--amber)",
        cyan: "var(--cyan)",
      },
      fontFamily: {
        sans: ["IBM Plex Sans", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
