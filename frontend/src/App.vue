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
        <RouterLink to="/results"  class="nav-link" active-class="active" @click="navOpen = false">正誤</RouterLink>
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
import { ref, onMounted } from 'vue'
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

onMounted(() => {
  checkOllama()
  setInterval(checkOllama, 30000)
})
</script>

<style>
:root {
  --bg-primary:   #0f172a;
  --bg-secondary: #1e293b;
  --bg-card:      #1e293b;
  --border:       #334155;
  --text-primary: #f1f5f9;
  --text-muted:   #94a3b8;
  --accent:       #6366f1;
  --accent-hover: #818cf8;
  --success:      #22c55e;
  --danger:       #ef4444;
  --warning:      #f59e0b;
  --radius:       12px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: 'Segoe UI', 'Hiragino Sans', 'Meiryo', sans-serif;
  font-size: 14px;
  line-height: 1.6;
}

.app { min-height: 100vh; display: flex; flex-direction: column; }

/* ナビゲーション */
.navbar {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 24px;
  height: 60px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 100;
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
}

/* ボタン */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.2s;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary  { background: var(--accent); color: #fff; }
.btn-primary:hover:not(:disabled) { background: var(--accent-hover); }
.btn-secondary { background: var(--border); color: var(--text-primary); }
.btn-secondary:hover:not(:disabled) { background: #475569; }
.btn-danger   { background: var(--danger); color: #fff; }
.btn-danger:hover:not(:disabled) { background: #dc2626; }
.btn-success  { background: var(--success); color: #fff; }

/* フォーム */
.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-label { font-size: 12px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; }
.form-input, .form-select, .form-textarea {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  padding: 8px 12px;
  font-size: 13px;
  width: 100%;
  transition: border-color 0.2s;
}
.form-input:focus, .form-select:focus, .form-textarea:focus {
  outline: none;
  border-color: var(--accent);
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
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
