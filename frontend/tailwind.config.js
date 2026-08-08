// Mint ramp — reused for the `mint`, `sky`, `green` and `emerald` scales so
// every "accent" and "success" colour in the app lands on the same green.
const MINT = {
  50: '#EAFFF6',
  100: '#D2FDEA',
  200: '#B6FBDC',
  300: '#7BF3C0',
  400: '#3FE39B',
  500: '#22D07E',
  600: '#15B96C',
  700: '#0E8F52',
  800: '#0A6B3E',
  900: '#07472A',
  950: '#042B19',
}

// Warm ramp for warnings — `yellow` is remapped onto amber so caution states
// read as deliberate against the mint rather than as a second accent.
const WARN = {
  50: '#FFFBEB',
  100: '#FEF3C7',
  200: '#FDE68A',
  300: '#FCD34D',
  400: '#FBBF24',
  500: '#F59E0B',
  600: '#D97706',
  700: '#B45309',
  800: '#92400E',
  900: '#78350F',
  950: '#451A03',
}

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // ── Core surfaces ────────────────────────────────────────────────
        panel: {
          bg: '#060E13',      // page background (deepest)
          card: '#0D1D25',    // card / panel surface
          rail: '#081419',    // sidebar rail
          raise: '#12282F',   // hovered / raised surface
          border: '#17333D',  // hairline borders
          accent: '#3FE39B',  // mint accent
        },
        // Mint accent ramp — primary brand colour.
        mint: MINT,
        aqua: '#22E5CE', // secondary glow / gradient partner

        // ── Legacy scale remaps ──────────────────────────────────────────
        // The app already uses `slate-*` for text/surfaces and `sky-*` for the
        // accent throughout. Rebinding both scales retints every existing
        // utility to the new theme instead of editing hundreds of call sites.
        slate: {
          50: '#F3FBF8',
          100: '#E7F5F1',
          200: '#CFE4E1',
          300: '#A6C2C6',
          400: '#7B989F',
          500: '#5F7E89',  // muted labels
          600: '#47636D',
          700: '#17333D',  // borders / raised chips
          800: '#0F222A',
          900: '#091820',
          950: '#060E13',
        },
        sky: MINT,
        // "Success" greens across the app land on the same mint as the accent.
        green: MINT,
        emerald: MINT,
        // Warnings use the amber ramp rather than Tailwind's default yellow.
        yellow: WARN,
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.7)',
        glow: '0 0 0 1px rgba(63,227,155,0.35), 0 0 28px -6px rgba(63,227,155,0.45)',
        rail: '0 8px 20px -8px rgba(34,208,126,0.55)',
      },
      backgroundImage: {
        'mint-grad': 'linear-gradient(135deg, #3FE39B 0%, #22D07E 55%, #15B96C 100%)',
        'card-grad': 'linear-gradient(160deg, rgba(23,51,61,0.55) 0%, rgba(13,29,37,0.9) 45%)',
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
