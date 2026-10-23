import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Vite runs the frontend during development and builds it for release.
export default defineConfig({
  // The React plugin lets Vite understand components and refresh them while editing.
  plugins: [react()],
  // Serve locally and forward API requests and live connections to Python.
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', ws: true } },
  },
  // Preview uses the same backend when checking a completed frontend build.
  preview: {
    host: '127.0.0.1',
    proxy: { '/api': { target: 'http://127.0.0.1:8000', ws: true } },
  },
})
