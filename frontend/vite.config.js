import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// FRONTEND-14: dev-server security headers. The Vite dev server is
// only intended for local + LAN preview, but we still want
// defense-in-depth so a stray injected script can't easily exfiltrate
// or get framed by an attacker on the same network.
//
// Notes:
//   - 'unsafe-eval' is required for Vite/HMR to work in dev. We
//     accept it here because the dev server is local-only.
//   - 'unsafe-inline' on style-src covers Vue's scoped style injection.
//   - X-Frame-Options=DENY blocks clickjacking from outside the origin.
//   - Referrer-Policy=no-referrer keeps Mermaid CDN-style prompts from
//     leaking the local URL to outbound requests.
const DEV_SECURITY_HEADERS = {
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'no-referrer',
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Content-Security-Policy': [
    "default-src 'self'",
    "script-src 'self' 'unsafe-eval'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self' ws: wss: http://localhost:* http://127.0.0.1:*",
    "frame-ancestors 'none'",
    "base-uri 'self'",
  ].join('; '),
}

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': resolve(__dirname, 'src') }
  },
  server: {
    host: '0.0.0.0',
    port: 1234,
    headers: DEV_SECURITY_HEADERS,
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
  },
  preview: {
    headers: DEV_SECURITY_HEADERS,
  },
})
