import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Everything the app talks to is proxied so it stays same-origin.
// Cross-origin caption tracks fail silently, so this matters.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_TARGET || 'http://localhost:8000'
  return {
    plugins: [react()],
    server: {
      host: true,
      proxy: {
        '/api': { target, changeOrigin: true },
        '/lessons': { target, changeOrigin: true },
        '/capture': { target, changeOrigin: true },
        '/ws': { target, changeOrigin: true, ws: true },
      },
    },
  }
})
