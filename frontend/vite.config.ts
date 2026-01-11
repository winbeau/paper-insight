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
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
        '/static': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
  }
})
