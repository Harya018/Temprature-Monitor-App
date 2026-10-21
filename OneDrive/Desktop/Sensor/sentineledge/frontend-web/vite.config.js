import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
    // Source maps expose the full frontend source when served from backend/static.
    // Off for production builds; set SOURCEMAP=true to build them for debugging.
    sourcemap: process.env.SOURCEMAP === 'true',
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:5000',
        ws: true,
      }
    }
  }
})
