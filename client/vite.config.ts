import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {}
const proxyTarget = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: proxyTarget, changeOrigin: true },
      '/mcp': { target: proxyTarget, changeOrigin: true },
    },
  },
})
