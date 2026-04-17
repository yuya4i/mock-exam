<template>
  <div class="app">
    <nav class="navbar">
      <div class="navbar-brand">
        <span class="brand-icon">🧠</span>
        <span class="brand-name">QuizGen</span>
        <span class="brand-sub">AI模擬問題生成</span>
      </div>
      <button class="navbar-hamburger" @click="navOpen = !navOpen" aria-label="メニュー">
        <span></span><span></span><span></span>
      </button>
      <div class="navbar-links" :class="{ open: navOpen }">
        <RouterLink to="/"         class="nav-link" active-class="active" @click="navOpen = false">問題生成</RouterLink>
        <RouterLink to="/database" class="nav-link" active-class="active" @click="navOpen = false">データベース</RouterLink>
        <RouterLink to="/results"  class="nav-link" active-class="active" @click="navOpen = false">分析</RouterLink>
        <RouterLink to="/settings" class="nav-link" active-class="active" @click="navOpen = false">設定</RouterLink>
      </div>
      <div class="ollama-status">
        <span :class="['status-dot', ollamaStatus]"></span>
        <span class="status-text">Ollama</span>
      </div>
    </nav>
    <main class="main-content">
      <RouterView />
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import api from '@/composables/useApi'

const ollamaStatus = ref('unknown')
const navOpen = ref(false)

async function checkOllama() {
  try {
    const res = await api.get('/health')
    ollamaStatus.value = res.data.ollama === 'connected' ? 'connected' : 'disconnected'
  } catch {
    ollamaStatus.value = 'disconnected'
  }
}

// FRONTEND-13: clear the interval on unmount AND on Vite HMR dispose.
// Without this, every hot-reload during dev installs another timer
// without cleaning the prior one — over a few minutes of edits the
// /api/health endpoint gets hammered by stale stacked intervals.
let _ollamaTimer = null

onMounted(() => {
  checkOllama()
  _ollamaTimer = setInterval(checkOllama, 30000)
})

onBeforeUnmount(() => {
  if (_ollamaTimer) clearInterval(_ollamaTimer)
  _ollamaTimer = null
})

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    if (_ollamaTimer) clearInterval(_ollamaTimer)
    _ollamaTimer = null
  })
}
</script>

<style>
:root {
  --bg-primary:   #0b1220;
  --bg-secondary: #131c2e;
  --bg-card:      #1a2438;
  --bg-card-hover:#1f2a42;
  --border:       #2c3a55;
  --border-strong:#3b4d70;
  --text-primary: #f1f5f9;
  --text-muted:   #94a3b8;
  --text-faint:   #64748b;
  --accent:       #6366f1;
  --accent-hover: #818cf8;
  --accent-glow:  rgba(99,102,241,0.35);
  --success:      #22c55e;
  --danger:       #ef4444;
  --warning:      #f59e0b;
  --radius:       12px;
  --radius-sm:    8px;
  --shadow-sm:    0 1px 3px rgba(0,0,0,0.18), 0 1px 2px rgba(0,0,0,0.10);
  --shadow-md:    0 4px 16px rgba(0,0,0,0.22), 0 2px 6px rgba(0,0,0,0.12);
  --shadow-lg:    0 12px 36px rgba(0,0,0,0.28), 0 4px 12px rgba(0,0,0,0.16);
  --transition:   180ms cubic-bezier(0.4, 0, 0.2, 1);
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background:
    radial-gradient(circle at 20% 0%, rgba(99,102,241,0.10), transparent 50%),
    radial-gradient(circle at 80% 100%, rgba(34,197,94,0.06), transparent 50%),
    var(--bg-primary);
  background-attachment: fixed;
  color: var(--text-primary);
  font-family: 'Inter', 'Segoe UI', 'Hiragino Sans', 'Meiryo', sans-serif;
  font-size: 14px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.app { min-height: 100vh; display: flex; flex-direction: column; }

/* ナビゲーション */
.navbar {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 24px;
  height: 60px;
  background: rgba(19, 28, 46, 0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 4px 20px rgba(0,0,0,0.20);
}

.navbar-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.brand-icon { font-size: 22px; }
.brand-name { font-size: 18px; font-weight: 700; color: var(--accent-hover); }
.brand-sub  { font-size: 11px; color: var(--text-muted); }

.navbar-hamburger {
  display: none;
  flex-direction: column;
  gap: 4px;
  background: none;
  border: none;
  cursor: pointer;
  padding: 6px;
  margin-left: auto;
}
.navbar-hamburger span {
  display: block;
  width: 20px;
  height: 2px;
  background: var(--text-muted);
  border-radius: 1px;
  transition: all 0.2s;
}

.navbar-links { display: flex; gap: 4px; }

.nav-link {
  padding: 6px 14px;
  border-radius: 8px;
  color: var(--text-muted);
  text-decoration: none;
  font-size: 13px;
  transition: all 0.2s;
  white-space: nowrap;
}
.nav-link:hover { color: var(--text-primary); background: rgba(255,255,255,0.05); }
.nav-link.active { color: var(--accent-hover); background: rgba(99,102,241,0.15); }

.ollama-status {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  margin-left: auto;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
}
.status-dot.connected    { background: var(--success); box-shadow: 0 0 6px var(--success); }
.status-dot.disconnected { background: var(--danger); }
.status-text { font-size: 12px; color: var(--text-muted); }

.main-content { flex: 1; width: 100%; }

/* ========== ナビバー レスポンシブ ========== */
@media (max-width: 768px) {
  .navbar { padding: 0 12px; gap: 8px; flex-wrap: wrap; height: auto; min-height: 52px; }
  .brand-sub { display: none; }
  .brand-name { font-size: 15px; }
  .brand-icon { font-size: 18px; }

  .navbar-hamburger { display: flex; }

  .navbar-links {
    display: none;
    flex-direction: column;
    width: 100%;
    gap: 2px;
    padding: 4px 0 8px;
    order: 10;
  }
  .navbar-links.open { display: flex; }
  .navbar-links .nav-link { padding: 10px 14px; font-size: 14px; }

  .ollama-status .status-text { display: none; }

}

/* 共通カード */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  box-shadow: var(--shadow-sm);
  transition: box-shadow var(--transition), border-color var(--transition);
}
.card:hover {
  box-shadow: var(--shadow-md);
}

/* ボタン */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px 18px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.01em;
  transition: background var(--transition), border-color var(--transition), box-shadow var(--transition), transform 80ms ease;
  user-select: none;
}
.btn:active:not(:disabled) { transform: translateY(1px); }
.btn:disabled { opacity: 0.45; cursor: not-allowed; }
.btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px var(--accent-glow);
}

.btn-primary {
  background: linear-gradient(135deg, var(--accent) 0%, #5256e8 100%);
  color: #fff;
  border-color: rgba(255,255,255,0.06);
  box-shadow: 0 1px 0 rgba(255,255,255,0.10) inset, 0 4px 14px rgba(99,102,241,0.30);
}
.btn-primary:hover:not(:disabled) {
  background: linear-gradient(135deg, var(--accent-hover) 0%, #6c70f0 100%);
  box-shadow: 0 1px 0 rgba(255,255,255,0.14) inset, 0 6px 20px rgba(99,102,241,0.40);
}
.btn-secondary {
  background: var(--bg-card-hover);
  color: var(--text-primary);
  border-color: var(--border-strong);
}
.btn-secondary:hover:not(:disabled) {
  background: #2a3858;
  border-color: var(--accent);
}
.btn-danger {
  background: linear-gradient(135deg, var(--danger) 0%, #d83a3a 100%);
  color: #fff;
  box-shadow: 0 4px 14px rgba(239,68,68,0.30);
}
.btn-danger:hover:not(:disabled) {
  background: linear-gradient(135deg, #f06464 0%, #dc2626 100%);
}
.btn-success { background: var(--success); color: #fff; }

/* フォーム */
.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-label { font-size: 12px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; }
.form-input, .form-select, .form-textarea {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  padding: 9px 12px;
  font-size: 13px;
  width: 100%;
  transition: border-color var(--transition), box-shadow var(--transition), background var(--transition);
}
.form-input::placeholder, .form-textarea::placeholder { color: var(--text-faint); }
.form-input:hover, .form-select:hover, .form-textarea:hover { border-color: var(--border-strong); }
.form-input:focus, .form-select:focus, .form-textarea:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-glow);
}
.form-textarea { resize: vertical; min-height: 80px; }

/* バッジ */
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
}
.badge-k1 { background: #1e3a5f; color: #60a5fa; }
.badge-k2 { background: #1a3a2a; color: #4ade80; }
.badge-k3 { background: #3a2a10; color: #fbbf24; }
.badge-k4 { background: #3a1a1a; color: #f87171; }

/* アラート */
.alert {
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 13px;
}
.alert-error   { background: rgba(239,68,68,0.1);  border: 1px solid rgba(239,68,68,0.3);  color: #fca5a5; }
.alert-success { background: rgba(34,197,94,0.1);  border: 1px solid rgba(34,197,94,0.3);  color: #86efac; }
.alert-info    { background: rgba(99,102,241,0.1); border: 1px solid rgba(99,102,241,0.3); color: #a5b4fc; }
.alert-warning { background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.35); color: #fcd34d; }

/* スピナー */
.spinner {
  display: inline-block;
  width: 16px; height: 16px;
  border: 2px solid rgba(255,255,255,0.2);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* スクロールバー */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 4px;
  border: 2px solid transparent;
  background-clip: padding-box;
}
::-webkit-scrollbar-thumb:hover {
  background: var(--border-strong);
  background-clip: padding-box;
  border: 2px solid transparent;
}
* { scrollbar-color: var(--border) transparent; scrollbar-width: thin; }

/* グローバルセレクション色 */
::selection { background: rgba(99,102,241,0.40); color: #fff; }
</style>
