import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': resolve(__dirname, 'src') }
  },
  server: {
    host: '0.0.0.0',
    port: 1234,
    proxy: {
      '/api': {
        target: process.env.API_PROXY_TARGET || 'http://localhost:4321',
        changeOrigin: true,
      }
    },
    watch: {
      usePolling: true,
      interval: 500,
    },
    hmr: {
      port: 1234,
    }
  }
})
