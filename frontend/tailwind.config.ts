import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "2rem", screens: { "2xl": "1400px" } },
    extend: {
      colors: {
        // MALE'DENIM Selvedge palette — DEFAULT keys preserve legacy single-name usage.
        ink: {
          DEFAULT: "#213033",
          950: "#0E1417",
          900: "#131B1F",
          800: "#1A242A",
          700: "#243036",
          600: "#33424A",
          500: "#4A5C66",
        },
        graphite: "#606060",
        steel: {
          DEFAULT: "#87A6B8",
          600: "#5E7E92",
          500: "#6F92A6",
          400: "#87A6B8",
          300: "#A6BECC",
        },
        concrete: "#E1E1DF",
        cloud:    "#F4F3F0",
        raw:      "#FAF9F6",
        navy: {
          DEFAULT: "#0C457A",
          700: "#23415C",
          600: "#2C5074",
          500: "#37618B",
        },
        terracotta: "#B4543F",
        ochre:      "#8A6A22",   // WCAG AA vs raw (5.4:1) / cloud (5.2:1)
        sage:       "#4F6B4C",   // WCAG AA-friendly vs raw/cloud (5.4:1)
        selvedge:   "#C8412B",   // brand signature — solo pespunte

        // Legacy aliases kept for non-Revenue pages
        cream:    "#F1EAD8",
        khaki:    "#7B6E42",
        teal:     "#036A73",
        rust:     "#B95902",
        crimson:  "#990012",

        // shadcn semantic
        border:      "hsl(var(--border))",
        input:       "hsl(var(--input))",
        ring:        "hsl(var(--ring))",
        background:  "hsl(var(--background))",
        foreground:  "hsl(var(--foreground))",
        primary:     { DEFAULT: "hsl(var(--primary))",     foreground: "hsl(var(--primary-foreground))" },
        secondary:   { DEFAULT: "hsl(var(--secondary))",   foreground: "hsl(var(--secondary-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        muted:       { DEFAULT: "hsl(var(--muted))",       foreground: "hsl(var(--muted-foreground))" },
        accent:      { DEFAULT: "hsl(var(--accent))",      foreground: "hsl(var(--accent-foreground))" },
        popover:     { DEFAULT: "hsl(var(--popover))",     foreground: "hsl(var(--popover-foreground))" },
        card:        { DEFAULT: "hsl(var(--card))",        foreground: "hsl(var(--card-foreground))" },
      },
      borderRadius: {
        DEFAULT: "6px",
        lg: "10px",
        md: "8px",
        sm: "4px",
      },
      fontFamily: {
        display: ['"Futura PT"', "Jost", "system-ui", "sans-serif"],
        sans:    ["var(--font-inter)", "Inter", "system-ui", "sans-serif"],
      },
      keyframes: {
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up":   { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
        "shimmer":        { "0%": { backgroundPosition: "-200% 0" }, "100%": { backgroundPosition: "200% 0" } },
        "fade-in":        { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-in-right": { from: { transform: "translateX(100%)" }, to: { transform: "translateX(0)" } },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up":   "accordion-up 0.2s ease-out",
        "shimmer":        "shimmer 1.4s ease-in-out infinite",
        "fade-in":        "fade-in 200ms ease-out",
        "slide-in-right": "slide-in-right 240ms cubic-bezier(0.32, 0.72, 0, 1)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
