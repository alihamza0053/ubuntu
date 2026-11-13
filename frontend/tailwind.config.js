// Every colour comes from a CSS variable in src/theme.css, so one class
// (text-slate-300, bg-mint-400/10…) renders right in both the dark and the
// light theme. The values are "R G B" triplets: <alpha-value> keeps Tailwind's
// opacity modifiers working.
const SHADES = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`
const ramp = (name) => Object.fromEntries(SHADES.map((s) => [s, v(`${name}-${s}`)]))

const MINT = ramp('mint')
const WARN = ramp('warn')

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // ── Surfaces ─────────────────────────────────────────────────────
        panel: {
          bg: v('panel-bg'),         // page background
          card: v('panel-card'),     // bento tile
          rail: v('panel-rail'),     // sidebar tile
          raise: v('panel-raise'),   // hovered / raised surface
          border: v('panel-border'), // hairlines
          accent: v('panel-accent'),
        },
        scrim: v('scrim'),
        aqua: v('aqua'),
        // Text on the mint gradient: dark green in both themes.
        ink: '#04231a',
        // Terminals and logs stay dark in every theme.
        term: '#04090c',

        // ── Scales ───────────────────────────────────────────────────────
        // The app uses slate-* for text and surfaces and mint/sky/green/emerald
        // for the accent; rebinding the scales themes every existing utility.
        slate: ramp('slate'),
        mint: MINT,
        sky: MINT,
        green: MINT,
        emerald: MINT,
        yellow: WARN,
        amber: WARN,
        red: ramp('red'),
        violet: ramp('violet'),
        lime: ramp('lime'),
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
      borderRadius: {
        tile: '1.5rem',   // bento tile
      },
      boxShadow: {
        card: 'var(--shadow-card)',
        glow: 'var(--shadow-lift)',
        lift: 'var(--shadow-lift)',
        pop: 'var(--shadow-pop)',
        rail: '0 8px 20px -8px rgba(34,208,126,0.55)',
      },
      backgroundImage: {
        'mint-grad': 'linear-gradient(135deg, #3FE39B 0%, #22D07E 55%, #15B96C 100%)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'pulse-ring': {
          '0%': { boxShadow: '0 0 0 0 rgba(63,227,155,0.5)' },
          '70%': { boxShadow: '0 0 0 8px rgba(63,227,155,0)' },
          '100%': { boxShadow: '0 0 0 0 rgba(63,227,155,0)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.25s ease-out both',
        'pulse-ring': 'pulse-ring 2s ease-out infinite',
      },
    },
  },
  plugins: [],
}
