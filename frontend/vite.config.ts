import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Backend port: 8010 by default (start scripts pass VITE_API_PORT when using another one).
const api = `http://127.0.0.1:${process.env.VITE_API_PORT || 8010}`

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: api,
        changeOrigin: true,
        ws: true,
      },
      '/uploads': {
        target: api,
        changeOrigin: true,
      },
    },
  },
})
