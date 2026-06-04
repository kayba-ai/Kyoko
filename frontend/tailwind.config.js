import animate from "tailwindcss-animate";

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["'Plus Jakarta Sans'", "Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: {
        // Sizes are rem-relative so the whole UI scales from one knob: the html
        // root font-size (see index.css). rem values mirror the prior px scale
        // at a 16px base; the root is nudged up so everything reads a tad bigger
        // (closer to kayba-hosted) without re-tuning each token.
        label: ["0.75rem", "1rem"], /* 12/16 */
        xs: ["0.75rem", "1rem"], /* 12/16 */
        sm: ["0.75rem", "1.125rem"], /* 12/18 */
        base: ["0.8125rem", "1.25rem"], /* 13/20 */
        md: ["0.875rem", "1.375rem"], /* 14/22 */
        lg: ["1rem", "1.5rem"], /* 16/24 */
        xl: ["1.25rem", "1.75rem"], /* 20/28 */
        "2xl": ["1.5rem", "2rem"], /* 24/32 */
      },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar))",
          foreground: "hsl(var(--sidebar-foreground))",
          border: "hsl(var(--sidebar-border))",
        },
        llm: "hsl(var(--llm))",
        tool: "hsl(var(--tool))",
        ok: "hsl(var(--ok))",
        warn: "hsl(var(--warn))",
        danger: "hsl(var(--danger))",
      },
      borderRadius: {
        sm: "calc(var(--radius) - 4px)", /* 2px */
        md: "calc(var(--radius) - 2px)", /* 4px */
        lg: "var(--radius)", /* 6px */
        xl: "calc(var(--radius) + 4px)", /* 10px */
        "2xl": "calc(var(--radius) + 8px)", /* 14px */
      },
      boxShadow: {
        xs: "0 1px 2px 0 hsl(223 20% 4% / 0.05)",
        soft: "0 1px 2px 0 hsl(223 20% 4% / 0.04), 0 1px 3px 0 hsl(223 20% 4% / 0.03)",
        card: "0 1px 2px 0 hsl(223 20% 4% / 0.04), 0 2px 8px -2px hsl(223 20% 4% / 0.06)",
        pop: "0 4px 16px -2px hsl(223 20% 4% / 0.12), 0 2px 6px -2px hsl(223 20% 4% / 0.08)",
      },
      keyframes: {
        "pulse-dot": { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.3" } },
        "fade-in": { from: { opacity: "0", transform: "translateY(2px)" }, to: { opacity: "1", transform: "translateY(0)" } },
      },
      animation: {
        "pulse-dot": "pulse-dot 1.8s ease-in-out infinite",
        "fade-in": "fade-in 140ms ease-out both",
      },
    },
  },
  plugins: [animate],
};
