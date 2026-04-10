<template>
  <div class="database-page">
    <!-- ヘッダー -->
    <div class="page-header">
      <h2 class="section-title">データベース</h2>
      <span class="total-count">{{ documentsStore.documents.length }} 件</span>
      <button class="btn btn-secondary" @click="documentsStore.fetchDocuments()" :disabled="documentsStore.loading" style="margin-left:auto">
        <span v-if="documentsStore.loading" class="spinner"></span>
        <span v-else>更新</span>
      </button>
    </div>

    <!-- 検索バー -->
    <div class="search-bar">
      <input
        v-model="documentsStore.search"
        class="form-input"
        placeholder="タイトルまたはURLで検索..."
      />
    </div>

    <!-- ローディング -->
    <div v-if="documentsStore.loading" class="loading-state">
      <div class="spinner" style="width:32px;height:32px;border-width:3px"></div>
      <span>読み込み中...</span>
    </div>

    <!-- エラー -->
    <div v-else-if="documentsStore.error" class="alert alert-error">
      {{ documentsStore.error }}
    </div>

    <!-- 空状態 -->
    <div v-else-if="documentsStore.filtered.length === 0" class="empty-state card">
      <span style="font-size:48px">📂</span>
      <p v-if="documentsStore.search">検索結果がありません。</p>
      <p v-else>保存済みのドキュメントがありません。</p>
      <RouterLink v-if="!documentsStore.search" to="/" class="btn btn-primary">問題生成ページで追加する</RouterLink>
    </div>

    <!-- ドキュメントグリッド -->
    <div v-else class="doc-grid">
      <div v-for="doc in documentsStore.filtered" :key="doc.id" class="doc-card card">
        <div class="doc-card-header">
          <span class="doc-title">{{ doc.title || '無題' }}</span>
          <span :class="['badge', sourceTypeBadge(doc.source_type)]">
            {{ sourceTypeLabel(doc.source_type) }}
          </span>
        </div>

        <div v-if="doc.url" class="doc-url">
          <a :href="doc.url" target="_blank" rel="noopener">{{ doc.url }}</a>
        </div>

        <div class="doc-meta">
          <span v-if="doc.page_count" class="meta-item">{{ doc.page_count }} ページ</span>
          <span v-if="doc.doc_types?.length" class="meta-item">
            {{ doc.doc_types.map(docTypeLabel).join(', ') }}
          </span>
          <span v-if="doc.scraped_at" class="meta-item">{{ formatDate(doc.scraped_at) }}</span>
        </div>

        <div class="doc-actions">
          <button class="btn btn-secondary btn-sm" @click="previewDocument(doc)">
            プレビュー
          </button>
          <button class="btn btn-primary btn-sm" @click="useInQuiz(doc)">
            問題生成に使用
          </button>
          <button class="btn btn-danger btn-sm" @click="confirmDelete(doc)">
            削除
          </button>
        </div>
      </div>
    </div>

    <!-- プレビューモーダル -->
    <div v-if="previewDoc" class="modal-overlay" @click.self="previewDoc = null">
      <div class="modal-content">
        <div class="modal-header">
          <h3>{{ previewDoc.title || '無題' }}</h3>
          <button class="btn btn-secondary" @click="previewDoc = null">閉じる</button>
        </div>
        <div v-if="previewLoading" class="loading-state" style="padding:40px">
          <div class="spinner" style="width:24px;height:24px;border-width:2px"></div>
          <span>読み込み中...</span>
        </div>
        <div v-else class="preview-content">
          <div class="preview-meta">
            <span v-if="previewDoc.url">URL: {{ previewDoc.url }}</span>
            <span v-if="previewDoc.page_count">{{ previewDoc.page_count }} ページ</span>
          </div>
          <pre class="preview-text">{{ previewContent }}</pre>
        </div>
      </div>
    </div>

    <!-- 削除確認ダイアログ -->
    <div v-if="deleteTarget" class="modal-overlay" @click.self="deleteTarget = null">
      <div class="modal-content modal-sm">
        <div class="modal-header">
          <h3>ドキュメントを削除</h3>
        </div>
        <p class="confirm-text">
          「{{ deleteTarget.title || '無題' }}」を削除しますか？この操作は取り消せません。
        </p>
        <div class="confirm-actions">
          <button class="btn btn-secondary" @click="deleteTarget = null">キャンセル</button>
          <button class="btn btn-danger" @click="executeDelete" :disabled="deleting">
            <span v-if="deleting" class="spinner"></span>
            削除する
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useDocumentsStore } from '@/stores'

const router         = useRouter()
const documentsStore = useDocumentsStore()

const previewDoc     = ref(null)
const previewContent = ref('')
const previewLoading = ref(false)
const deleteTarget   = ref(null)
const deleting       = ref(false)

const docTypeLabelMap = { table: 'テーブル', csv: 'CSV', pdf: 'PDF', png: '画像' }
const docTypeLabel    = (v) => docTypeLabelMap[v] || v

function sourceTypeBadge(type) {
  if (type === 'url' || type === 'url_deep') return 'badge-k2'
  if (type === 'text') return 'badge-k3'
  return 'badge-k1'
}

function sourceTypeLabel(type) {
  if (type === 'url')      return 'URL'
  if (type === 'url_deep') return 'URL (深層)'
  if (type === 'text')     return 'TEXT'
  return type || '不明'
}

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('ja-JP', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

async function previewDocument(doc) {
  previewDoc.value     = doc
  previewContent.value = ''
  previewLoading.value = true
  try {
    const full = await documentsStore.getDocument(doc.id)
    previewContent.value = full.content || '(コンテンツなし)'
  } catch (e) {
    previewContent.value = 'エラー: ' + e.message
  } finally {
    previewLoading.value = false
  }
}

function useInQuiz(doc) {
  // Navigate to generate page with source prefilled
  router.push({ name: 'generate', query: { source: doc.url || doc.id } })
}

function confirmDelete(doc) {
  deleteTarget.value = doc
}

async function executeDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await documentsStore.deleteDocument(deleteTarget.value.id)
    deleteTarget.value = null
  } catch (e) {
    alert('削除に失敗しました: ' + e.message)
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  documentsStore.fetchDocuments()
})
</script>

<style scoped>
.database-page { display: flex; flex-direction: column; gap: 16px; padding: 24px; max-width: 1400px; margin: 0 auto; width: 100%; }

.page-header { display: flex; align-items: center; gap: 12px; }
.section-title { font-size: 16px; font-weight: 700; }
.total-count { font-size: 12px; color: var(--text-muted); }

.search-bar { max-width: 400px; }

.loading-state { display: flex; align-items: center; gap: 12px; color: var(--text-muted); padding: 40px; justify-content: center; }

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 60px;
  text-align: center;
  color: var(--text-muted);
}

/* ドキュメントグリッド */
.doc-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 14px;
}

.doc-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: border-color 0.2s;
}
.doc-card:hover { border-color: var(--accent); }

.doc-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.doc-title {
  font-weight: 600;
  font-size: 14px;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-url {
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.doc-url a {
  color: var(--accent);
  text-decoration: none;
}
.doc-url a:hover { text-decoration: underline; }

.doc-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 11px;
  color: var(--text-muted);
}

.doc-actions {
  display: flex;
  gap: 8px;
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}
.btn-sm {
  padding: 4px 10px;
  font-size: 11px;
}

/* モーダル */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.7);
  z-index: 200;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 24px;
  overflow-y: auto;
}
.modal-content {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  width: 100%;
  max-width: 800px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.modal-sm { max-width: 440px; }
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.modal-header h3 { font-size: 16px; font-weight: 700; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.preview-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 12px;
}
.preview-text {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 60vh;
  overflow-y: auto;
  font-family: inherit;
}

.confirm-text {
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
}
.confirm-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}
</style>
