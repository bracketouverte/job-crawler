import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        // The FastAPI backend's own default PORT (config.py) is 3000, not
        // vite's own port — override via VITE_BACKEND_URL for container-to-
        // container setups where the backend isn't reachable at localhost.
        target: process.env.VITE_BACKEND_URL ?? 'http://localhost:3000',
        changeOrigin: true,
      },
    },
  },
})
