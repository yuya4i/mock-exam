<template>
  <div class="settings-page">
    <h2 class="section-title">設定</h2>

    <!-- Ollama接続設定 -->
    <div class="card">
      <h3 class="card-title">Ollama 接続設定</h3>
      <div class="form-group">
        <label class="form-label">Ollama ベースURL</label>
        <div class="url-row">
          <input v-model="ollamaUrl" class="form-input" placeholder="http://localhost:11434" />
          <button class="btn btn-primary" @click="saveAndTest">保存 & 接続テスト</button>
        </div>
        <p class="form-hint">Dockerコンテナ内からホストのOllamaに接続する場合: <code>http://host.docker.internal:11434</code></p>
      </div>
      <div v-if="testResult" :class="['alert', testResult.ok ? 'alert-success' : 'alert-error']" style="margin-top:12px">
        {{ testResult.message }}
      </div>
    </div>

    <!-- 利用可能モデル一覧 -->
    <div class="card">
      <h3 class="card-title">インストール済みモデル</h3>
      <button class="btn btn-secondary" @click="modelsStore.fetchModels()" :disabled="modelsStore.loading">
        <span v-if="modelsStore.loading" class="spinner"></span>
        モデル一覧を更新
      </button>
      <div v-if="modelsStore.models.length > 0" class="model-table">
        <table>
          <thead>
            <tr>
              <th>モデル名</th>
              <th>サイズ</th>
              <th>更新日時</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in modelsStore.models" :key="m.name">
              <td><code>{{ m.name }}</code></td>
              <td>{{ formatSize(m.size) }}</td>
              <td>{{ formatDate(m.modified) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else-if="!modelsStore.loading" class="alert alert-info" style="margin-top:12px">
        モデルが見つかりません。<code>ollama pull &lt;model&gt;</code> でモデルをインストールしてください。
      </div>
    </div>

    <!-- アプリ情報 -->
    <div class="card">
      <h3 class="card-title">アプリ情報</h3>
      <table class="info-table">
        <tr><td>バージョン</td><td>1.0.0</td></tr>
        <tr><td>フロントエンド</td><td>Vue.js 3 + Vite 6.4.2</td></tr>
        <tr><td>バックエンド</td><td>Flask 3.0 (Python 3.11)</td></tr>
        <tr><td>HTTP クライアント</td><td>axios 1.15.0（CVE修正済み）</td></tr>
        <tr><td>AI エンジン</td><td>Ollama（ローカル）</td></tr>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useSettingsStore, useModelsStore } from '@/stores'
import api from '@/composables/useApi'

const settingsStore = useSettingsStore()
const modelsStore   = useModelsStore()

const ollamaUrl  = ref(settingsStore.ollamaUrl)
const testResult = ref(null)

async function saveAndTest() {
  settingsStore.setOllamaUrl(ollamaUrl.value)
  testResult.value = null
  try {
    const res = await api.get('/health')
    const ok  = res.data.ollama === 'connected'
    testResult.value = {
      ok,
      message: ok
        ? `✓ Ollama に接続できました（${res.data.ollama_url}）`
        : `✗ Ollama に接続できません。URLを確認してください。`,
    }
    if (ok) modelsStore.fetchModels()
  } catch (e) {
    testResult.value = { ok: false, message: `✗ ${e.message}` }
  }
}

function formatSize(bytes) {
  if (!bytes) return '-'
  const gb = bytes / 1024 ** 3
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / 1024 ** 2).toFixed(0)} MB`
}

function formatDate(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('ja-JP', {
    year: 'numeric', month: '2-digit', day: '2-digit',
  })
}
</script>

<style scoped>
.settings-page { display: flex; flex-direction: column; gap: 20px; padding: 24px; max-width: 1400px; margin: 0 auto; width: 100%; }
.section-title { font-size: 16px; font-weight: 700; }
.card-title    { font-size: 14px; font-weight: 700; margin-bottom: 14px; }

.url-row { display: flex; gap: 8px; }
.url-row .form-input { flex: 1; }

.form-hint { font-size: 12px; color: var(--text-muted); margin-top: 6px; }
.form-hint code { background: var(--bg-primary); padding: 2px 6px; border-radius: 4px; font-size: 11px; }

.model-table { margin-top: 12px; overflow-x: auto; }
.model-table table { width: 100%; border-collapse: collapse; font-size: 13px; }
.model-table th, .model-table td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}
.model-table th { color: var(--text-muted); font-size: 11px; text-transform: uppercase; }
.model-table code { background: var(--bg-primary); padding: 2px 6px; border-radius: 4px; }

.info-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.info-table td { padding: 8px 12px; border-bottom: 1px solid var(--border); }
.info-table td:first-child { color: var(--text-muted); width: 180px; }
</style>
