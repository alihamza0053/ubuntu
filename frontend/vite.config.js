import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Production build is served by FastAPI from backend/static/.
// In dev, /api and /ws are proxied to the backend on port 8765.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8765', ws: true },
    },
  },
})
