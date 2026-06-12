/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Dark panel palette
        panel: {
          bg: '#0f172a',      // page background (slate-900)
          card: '#1e293b',    // card background (slate-800)
          border: '#334155',  // borders (slate-700)
          accent: '#38bdf8',  // sky-400
        },
      },
    },
  },
  plugins: [],
}
