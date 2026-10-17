import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  const cwd = (globalThis as { process?: { cwd?: () => string } }).process?.cwd?.() ?? '.'
  const env = loadEnv(mode, cwd, 'VITE_')
  const proxyTarget = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [vue(), tailwindcss()],
    server: {
      port: 5173,
      proxy: {
        '/api': { target: proxyTarget, changeOrigin: true },
        '/mcp': { target: proxyTarget, changeOrigin: true },
      },
    },
  }
})
