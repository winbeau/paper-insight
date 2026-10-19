import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(() => {
  const base = process.env.VITE_BASE ?? '/'

  return {
    base,
    plugins: [
      vue(),
      tailwindcss(),
    ],
    server: {
      proxy: {
        // Backend dev server: `uv run uvicorn app.main:app --port 8000` (routes live under /api)
        '/api': {
          target: process.env.VITE_DEV_API_TARGET ?? 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
  }
})
