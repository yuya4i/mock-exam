<template>
  <div class="generate-page">
    <!-- 左サイドバー -->
    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed, 'mobile-open': sidebarMobileOpen }">
      <div class="sidebar-header">
        <span class="sidebar-title" v-if="!sidebarCollapsed">保存済みコンテンツ</span>
        <button class="sidebar-toggle" @click="toggleSidebar" :title="sidebarCollapsed ? '展開' : '折りたたみ'">
          {{ sidebarCollapsed ? '▶' : '◀' }}
        </button>
        <button v-if="!sidebarCollapsed" class="btn-icon" @click="refreshDocuments" :disabled="documentsLoading" title="更新">
          <span v-if="documentsLoading" class="spinner" style="width:12px;height:12px"></span>
          <span v-else>↻</span>
        </button>
      </div>
      <div v-if="!sidebarCollapsed" class="sidebar-list">
        <div v-if="documents.length === 0" class="sidebar-empty">
          コンテンツがありません
        </div>
        <div
          v-for="doc in documents"
          :key="doc.id"
          class="sidebar-item"
          :class="{ active: selectedDocId === doc.id }"
          @click="selectDocument(doc)"
          :title="doc.title || doc.url || '無題'"
        >
          <span class="sidebar-item-icon">{{ sourceIcon(doc.source_type) }}</span>
          <span class="sidebar-item-text">{{ doc.title || doc.url || '無題' }}</span>
        </div>
      </div>
      <!-- Collapsed mode: just icons -->
      <div v-if="sidebarCollapsed" class="sidebar-list-collapsed">
        <div
          v-for="doc in documents"
          :key="doc.id"
          class="sidebar-item-icon-only"
          :class="{ active: selectedDocId === doc.id }"
          @click="selectDocument(doc)"
          :title="doc.title || doc.url || '無題'"
        >
          {{ sourceIcon(doc.source_type) }}
        </div>
      </div>
    </aside>

    <!-- モバイル用サイドバートグル -->
    <button class="mobile-sidebar-btn" @click="sidebarMobileOpen = !sidebarMobileOpen">
      ☰ コンテンツ
    </button>

    <!-- 中央: 設定フォーム + 結果 -->
    <div class="center-column">
      <!-- 選択中ドキュメントの生成済み問題セット -->
      <div v-if="selectedDocId && (savedSessions.length > 0 || loadingSavedSessions)" class="card saved-sessions-panel">
        <div class="saved-sessions-header">
          <span class="saved-sessions-title">📚 この資料で生成済みの問題セット</span>
          <span v-if="loadingSavedSessions" class="spinner" style="width:12px;height:12px"></span>
          <span v-else class="saved-count">{{ savedSessions.length }}件</span>
        </div>
        <div class="saved-sessions-list">
          <button
            v-for="s in savedSessions"
            :key="s.session_id"
            class="saved-session-item"
            :class="{ active: selectedSessionId === s.session_id }"
            @click="loadSavedSession(s.session_id)"
          >
            <div class="saved-session-main">
              <span class="saved-session-meta">{{ formatDate(s.generated_at) }}</span>
              <span class="saved-session-model">🤖 {{ s.model }}</span>
              <span class="saved-session-count">{{ s.question_count }}問</span>
              <span class="saved-session-diff" :class="`diff-${s.difficulty}`">
                {{ difficultyLabel(s.difficulty) }}
              </span>
            </div>
            <div v-if="s.score_total" class="saved-session-score" :class="scoreColorClass(s.score_correct, s.score_total)">
              {{ s.score_correct }}/{{ s.score_total }}
              ({{ Math.round((s.score_correct / s.score_total) * 100) }}%)
            </div>
            <div v-else class="saved-session-score pending">未回答</div>
          </button>
        </div>
      </div>

      <div class="card config-panel">
        <h2 class="section-title">問題生成設定</h2>

        <div class="config-grid">
          <!-- コンテンツソース -->
          <div class="form-group full-width">
            <label class="form-label">コンテンツソース（URL または テキスト）</label>
            <div class="source-input-row">
              <input
                v-model="params.source"
                class="form-input"
                placeholder="https://example.com/docs または 直接テキストを入力..."
                @keydown.enter="previewContent"
              />
              <button class="btn btn-secondary" @click="previewContent" :disabled="!params.source || previewing">
                <span v-if="previewing" class="spinner"></span>
                <span v-else>プレビュー</span>
              </button>
            </div>

            <!-- 既取得URL通知 -->
            <div v-if="existingDocument" class="alert alert-info already-scraped-notice">
              <div class="already-scraped-title">
                ⚠ このURLは既に取得済みです
              </div>
              <div class="already-scraped-meta">
                <span>📅 {{ formatScrapedAt(existingDocument.scraped_at) }} 取得</span>
                <span>📄 {{ existingDocument.page_count || 1 }} ページ</span>
              </div>
              <div class="already-scraped-actions">
                <button class="btn btn-primary" @click="useExistingDocument">
                  保存済みデータを使う
                </button>
                <button class="btn btn-secondary" @click="dismissExistingDocument">
                  再スクレイピング
                </button>
              </div>
            </div>

            <!-- スクレイピング詳細設定（URLの場合のみ表示） -->
            <div v-if="isUrl" class="scrape-options">
              <div class="scrape-row">
                <!-- 階層数 -->
                <div class="scrape-field">
                  <label class="form-label-sm">
                    スクレイピング階層数
                    <span class="badge badge-k4">Max 8</span>
                  </label>
                  <div class="depth-control">
                    <button class="depth-btn" @click="decreaseDepth" :disabled="params.depth <= 1">−</button>
                    <span class="depth-value">{{ params.depth }}</span>
                    <button class="depth-btn" @click="increaseDepth" :disabled="params.depth >= 8">＋</button>
                    <span class="depth-hint">階層</span>
                  </div>
                  <p class="field-hint">指定URLから{{ params.depth }}階層分のリンクを辿って収集します（1回のみ実行）</p>
                </div>

                <!-- ドキュメント種別 -->
                <div class="scrape-field">
                  <label class="form-label-sm">対象ドキュメント種別</label>
                  <div class="doc-type-group">
                    <label
                      v-for="dt in docTypeOptions"
                      :key="dt.value"
                      class="doc-type-label"
                      :class="{ active: params.doc_types.includes(dt.value) }"
                    >
                      <input type="checkbox" :value="dt.value" v-model="params.doc_types" />
                      <span class="doc-type-icon">{{ dt.icon }}</span>
                      <span>{{ dt.label }}</span>
                    </label>
                  </div>
                  <p class="field-hint">camoufox（ボット検出回避）で取得します</p>
                </div>
              </div>
            </div>

            <!-- プレビュー表示 -->
            <div v-if="preview" class="preview-box">
              <div class="preview-header">
                <span class="preview-title">{{ preview.title }}</span>
                <span class="badge" :class="preview.type === 'url_deep' ? 'badge-k3' : 'badge-k2'">
                  {{ preview.type === 'url_deep' ? `URL (${preview.depth}階層)` : 'TEXT' }}
                </span>
                <span v-if="preview.page_count" class="badge badge-k1">
                  {{ preview.page_count }}ページ
                </span>
              </div>
              <!-- 収集ドキュメント種別 -->
              <div v-if="preview.doc_types?.length" class="doc-types-found">
                <span class="doc-types-label">取得種別:</span>
                <span
                  v-for="dt in preview.doc_types"
                  :key="dt"
                  class="doc-type-badge"
                >{{ docTypeLabel(dt) }}</span>
              </div>
              <!-- 収集ページ一覧 -->
              <details v-if="preview.pages?.length > 1" class="pages-detail">
                <summary>収集ページ一覧 ({{ preview.pages.length }}件)</summary>
                <ul class="pages-list">
                  <li v-for="p in preview.pages" :key="p.url">
                    <span class="page-depth">Lv.{{ p.depth }}</span>
                    <a :href="p.url" target="_blank" rel="noopener">{{ p.title || p.url }}</a>
                  </li>
                </ul>
              </details>
              <p class="preview-text">{{ preview.preview }}</p>
            </div>
            <div v-if="previewError" class="alert alert-error">{{ previewError }}</div>
          </div>

          <!-- モデル選択 -->
          <div class="form-group">
            <label class="form-label">Ollamaモデル</label>
            <div class="model-row">
              <select v-model="params.model" class="form-select">
                <option value="" disabled>モデルを選択...</option>
                <option v-for="m in modelsStore.models" :key="m.name" :value="m.name">
                  {{ m.name }} ({{ formatSize(m.size) }})
                </option>
              </select>
              <button class="btn btn-secondary" @click="modelsStore.fetchModels()" :disabled="modelsStore.loading">
                <span v-if="modelsStore.loading" class="spinner"></span>
                <span v-else>↻</span>
              </button>
            </div>
            <div v-if="modelsStore.error" class="alert alert-error" style="margin-top:6px">{{ modelsStore.error }}</div>
            <div v-if="modelsStore.models.length === 0 && !modelsStore.loading" class="alert alert-info" style="margin-top:6px">
              モデルが見つかりません。Ollamaが起動しているか確認してください。
            </div>
          </div>

          <!-- 問題数 -->
          <div class="form-group">
            <label class="form-label">問題数（1〜20）</label>
            <input v-model.number="params.count" type="number" min="1" max="20" class="form-input" />
          </div>

          <!-- 知識レベル -->
          <div class="form-group">
            <label class="form-label">知識レベル</label>
            <div class="checkbox-group">
              <label v-for="lv in ['K1','K2','K3','K4']" :key="lv" class="checkbox-label">
                <input type="checkbox" :value="lv" v-model="params.levels" />
                <span :class="['badge', `badge-${lv.toLowerCase()}`]">{{ lv }}</span>
              </label>
            </div>
          </div>

          <!-- 難易度 -->
          <div class="form-group">
            <label class="form-label">難易度</label>
            <div class="radio-group">
              <label v-for="d in difficulties" :key="d.value" class="radio-label">
                <input type="radio" :value="d.value" v-model="params.difficulty" />
                <span>{{ d.label }}</span>
              </label>
            </div>
          </div>
        </div>

        <div class="generate-actions">
          <button
            class="btn btn-primary generate-btn"
            @click="generate"
            :disabled="!canGenerate"
          >
            <span v-if="quizStore.generating" class="spinner"></span>
            <span v-else>&#10024;</span>
            {{ quizStore.generating ? '生成中...' : '問題を生成する' }}
          </button>
          <button v-if="quizStore.result" class="btn btn-secondary" @click="quizStore.reset()">
            リセット
          </button>
        </div>

        <div v-if="quizStore.error" class="alert alert-error" style="margin-top:12px">
          {{ quizStore.error }}
        </div>
      </div>

      <!-- 生成ステップインジケーター -->
      <div v-if="quizStore.generating" class="generating-steps card">
        <div class="steps-row">
          <div class="step" :class="stepClass(0)">
            <span class="step-num">①</span>
            <span class="step-label">コンテンツ取得</span>
            <span class="step-icon">
              <span v-if="currentStep === 0" class="spinner" style="width:12px;height:12px"></span>
              <span v-else-if="currentStep > 0" style="color:var(--success)">&#10003;</span>
            </span>
          </div>
          <span class="step-arrow">→</span>
          <div class="step" :class="stepClass(1)">
            <span class="step-num">②</span>
            <span class="step-label">スクレイピング</span>
            <span class="step-icon">
              <span v-if="currentStep === 1" class="spinner" style="width:12px;height:12px"></span>
              <span v-else-if="currentStep > 1" style="color:var(--success)">&#10003;</span>
            </span>
          </div>
          <span class="step-arrow">→</span>
          <div class="step" :class="stepClass(2)">
            <span class="step-num">③</span>
            <span class="step-label">AI問題生成</span>
            <span class="step-icon">
              <span v-if="currentStep === 2" class="spinner" style="width:12px;height:12px"></span>
              <span v-else-if="currentStep > 2" style="color:var(--success)">&#10003;</span>
            </span>
          </div>
          <span class="step-arrow">→</span>
          <div class="step" :class="stepClass(3)">
            <span class="step-num">④</span>
            <span class="step-label">完了</span>
            <span class="step-icon">
              <span v-if="currentStep >= 3" style="color:var(--success)">&#10003;</span>
            </span>
          </div>
        </div>
        <!-- 1問ずつ生成のプログレスバー -->
        <div v-if="quizStore.progress.status === 'generating'" class="gen-progress">
          <div class="gen-progress-bar">
            <div
              class="gen-progress-fill"
              :style="{ width: genProgressPct + '%' }"
            ></div>
          </div>
          <span class="gen-progress-text">
            {{ quizStore.progress.current }} / {{ quizStore.progress.total }} 問生成中...
          </span>
        </div>
        <p v-else class="steps-detail">{{ stepDetail }}</p>
      </div>

      <!-- 結果（生成中でも到着した問題を順次表示） -->
      <div v-if="quizStore.result" class="result-section">
        <!-- スコアサマリー（全問解答後） -->
        <div class="card score-card" v-if="answeredAll && !quizStore.generating">
          <div class="score-display">
            <span class="score-num">{{ quizStore.score?.correct }}</span>
            <span class="score-sep">/</span>
            <span class="score-total">{{ quizStore.score?.total }}</span>
          </div>
          <div class="score-label">正解数</div>
          <div class="score-pct">{{ Math.round((quizStore.score?.correct / quizStore.score?.total) * 100) }}%</div>
        </div>

        <!-- メタ情報 -->
        <div class="result-meta">
          <span>{{ quizStore.result.source_info?.title }}</span>
          <span v-if="quizStore.result.model">{{ quizStore.result.model }}</span>
          <span>{{ quizStore.result.questions?.length }}問{{ quizStore.generating ? ' (生成中...)' : '' }}</span>
          <span v-if="quizStore.result.source_info?.depth > 1">
            {{ quizStore.result.source_info.depth }}階層 / {{ quizStore.result.source_info.page_count }}ページ収集
          </span>
          <span v-if="quizStore.result.source_info?.doc_types?.length">
            {{ quizStore.result.source_info.doc_types.map(docTypeLabel).join(' / ') }}
          </span>
          <button v-if="!quizStore.generating" class="btn btn-secondary" style="margin-left:auto" @click="quizStore.revealAll()">
            全解答を表示
          </button>
          <button v-else class="btn btn-danger" style="margin-left:auto" @click="quizStore.abort()">
            生成を中止
          </button>
        </div>

        <!-- 問題カード一覧（1問ずつリアルタイム追加される） -->
        <TransitionGroup name="question-fade" tag="div" class="questions-list">
          <QuestionCard
            v-for="(q, i) in quizStore.result.questions"
            :key="q.id"
            :question="q"
            :index="i"
            :user-answer="quizStore.userAnswers[q.id]"
            :revealed="quizStore.revealed[q.id]"
            :source-info="quizStore.result.source_info"
            @answer="quizStore.setAnswer(q.id, $event)"
            @reveal="quizStore.revealAnswer(q.id)"
          />
        </TransitionGroup>
      </div>
    </div>

    <!-- 右パネル: スクレイピング経過 -->
    <aside class="progress-panel" :class="{ 'mobile-open': progressMobileOpen }">
      <div class="progress-header">
        <span class="progress-title">スクレイピング経過</span>
        <button class="mobile-close-btn" @click="progressMobileOpen = false">&#10005;</button>
      </div>

      <!-- スクレイピング中 or 完了 -->
      <div v-if="scrapeStore.events.length > 0" class="progress-content">
        <div class="progress-summary">
          <span v-if="scrapeStore.isScraping" class="spinner" style="width:12px;height:12px"></span>
          <span v-else style="color:var(--success)">&#10003;</span>
          <span>{{ scrapeStore.summary.pagesFound }} ページ取得済み</span>
        </div>

        <div class="progress-list">
          <div
            v-for="(ev, idx) in scrapeStore.events"
            :key="idx"
            class="progress-item"
            :class="{ done: ev.status === 'done', error: ev.status === 'error' }"
          >
            <span class="progress-depth" v-if="ev.depth !== undefined">Lv.{{ ev.depth }}</span>
            <span class="progress-url" v-if="ev.url" :title="ev.url">{{ truncateUrl(ev.url) }}</span>
            <span class="progress-url" v-else-if="ev.title">{{ ev.title }}</span>
            <span class="progress-status">
              <span v-if="ev.status === 'loading'" class="spinner" style="width:10px;height:10px"></span>
              <span v-else-if="ev.status === 'done'" style="color:var(--success)">&#10003;</span>
              <span v-else-if="ev.status === 'error'" style="color:var(--danger)">&#10005;</span>
            </span>
          </div>
        </div>

        <div v-if="scrapeStore.error" class="alert alert-error" style="margin-top:8px;font-size:12px">
          {{ scrapeStore.error }}
        </div>
      </div>

      <!-- アイドル状態 -->
      <div v-else class="progress-idle">
        <p>スクレイピング開始後に経過が表示されます</p>
      </div>
    </aside>

    <!-- モバイル用右パネルトグル -->
    <button class="mobile-progress-btn" @click="progressMobileOpen = !progressMobileOpen" v-if="scrapeStore.events.length > 0 || scrapeStore.isScraping">
      {{ scrapeStore.isScraping ? '経過...' : '経過' }}
      <span v-if="scrapeStore.isScraping" class="spinner" style="width:10px;height:10px"></span>
    </button>

    <!-- モバイルオーバーレイ -->
    <div v-if="sidebarMobileOpen" class="mobile-overlay" @click="sidebarMobileOpen = false"></div>
    <div v-if="progressMobileOpen" class="mobile-overlay" @click="progressMobileOpen = false"></div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'

import { useQuizStore, useModelsStore, useDocumentsStore, useScrapeProgressStore, useResultsStore } from '@/stores'
import QuestionCard from '@/components/QuestionCard.vue'
import api from '@/composables/useApi'

const route        = useRoute()
const quizStore    = useQuizStore()
const modelsStore  = useModelsStore()
const docsStore    = useDocumentsStore()
const scrapeStore  = useScrapeProgressStore()
const resultsStore = useResultsStore()

// 選択中ドキュメントの生成済みセッション一覧
const savedSessions = ref([])
const loadingSavedSessions = ref(false)
const selectedSessionId = ref(null)

const params = ref({
  source:     '',
  model:      '',
  count:      5,
  levels:     ['K2', 'K3', 'K4'],
  difficulty: 'medium',
  depth:      1,
  doc_types:  ['table', 'csv', 'pdf', 'png'],
})

const difficulties = [
  { value: 'easy',   label: '易しい' },
  { value: 'medium', label: '普通'   },
  { value: 'hard',   label: '難しい' },
]

const docTypeOptions = [
  { value: 'table', label: 'テーブル', icon: '📊' },
  { value: 'csv',   label: 'CSV',      icon: '📋' },
  { value: 'pdf',   label: 'PDF',      icon: '📄' },
  { value: 'png',   label: '画像',     icon: '🖼️' },
]

const docTypeLabelMap = { table: 'テーブル', csv: 'CSV', pdf: 'PDF', png: '画像' }
const docTypeLabel = (v) => docTypeLabelMap[v] || v

const preview      = ref(null)
const previewError = ref(null)
const previewing   = ref(false)

// 既に取得済みURLの検出結果
const existingDocument = ref(null)
let existingDocumentTimer = null
// 「保存済みデータを使う」「再スクレイピング」実行直後は再検知を抑止するURL
let suppressedUrl = null

// サイドバー状態
const sidebarCollapsed  = ref(false)
const sidebarMobileOpen = ref(false)
const progressMobileOpen = ref(false)
const selectedDocId     = ref(null)
const documents         = ref([])
const documentsLoading  = ref(false)

const isUrl = computed(() =>
  params.value.source.startsWith('http://') ||
  params.value.source.startsWith('https://')
)

// ---- ステップ進捗管理 ----
// 0: コンテンツ取得, 1: スクレイピング, 2: AI問題生成, 3: 完了
const currentStep = ref(0)

const stepDetail = computed(() => {
  switch (currentStep.value) {
    case 0: return 'コンテンツソースを解析しています...'
    case 1: return `ページをスクレイピング中... (${scrapeStore.summary.pagesFound}ページ取得済み)`
    case 2: return 'AIが問題を1問ずつ生成しています...'
    case 3: return '生成完了!'
    default: return ''
  }
})

const genProgressPct = computed(() => {
  const p = quizStore.progress
  if (!p.total) return 0
  return Math.round((p.current / p.total) * 100)
})

function stepClass(step) {
  if (currentStep.value === step) return 'active'
  if (currentStep.value > step) return 'done'
  return 'pending'
}

// ストアの状態を監視してステップを自動進行
watch(() => scrapeStore.isScraping, (val) => {
  if (val && currentStep.value < 1) currentStep.value = 1
})
watch(() => scrapeStore.events.length, () => {
  const last = scrapeStore.events[scrapeStore.events.length - 1]
  if (last?.type === 'done' && currentStep.value < 2) currentStep.value = 2
})
watch(() => quizStore.progress.status, (val) => {
  if (val === 'generating' && currentStep.value < 2) currentStep.value = 2
  if (val === 'done') currentStep.value = 3
})
watch(() => quizStore.generating, (val) => {
  if (!val && quizStore.result) currentStep.value = 3
})

const canGenerate = computed(() =>
  params.value.source &&
  params.value.model &&
  params.value.count >= 1 &&
  params.value.levels.length > 0 &&
  params.value.doc_types.length > 0 &&
  !quizStore.generating
)

const answeredAll = computed(() => {
  if (!quizStore.result?.questions) return false
  return quizStore.result.questions.every(
    (q) => quizStore.userAnswers[q.id] !== undefined
  )
})

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

function sourceIcon(type) {
  if (type === 'url' || type === 'url_deep') return '🌐'
  if (type === 'text') return '📝'
  return '📄'
}

async function selectDocument(doc) {
  selectedDocId.value = doc.id
  params.value.source = doc.url || doc.title || ''
  sidebarMobileOpen.value = false

  // 生成済みセッションを取得
  savedSessions.value = []
  selectedSessionId.value = null
  loadingSavedSessions.value = true
  try {
    const res = await api.get('/results', { params: { document_id: doc.id } })
    savedSessions.value = res.data.sessions || []
  } catch (_) {
    savedSessions.value = []
  } finally {
    loadingSavedSessions.value = false
  }
}

async function loadSavedSession(sessionId) {
  selectedSessionId.value = sessionId
  try {
    const data = await resultsStore.getSession(sessionId)
    // quizStore.result の構造に合わせる
    quizStore.result = {
      session_id:  data.session_id,
      model:       data.model,
      questions:   data.questions || [],
      source_info: data.source_info || {
        title:      data.source_title,
        type:       data.source_type,
        source:     (documents.value.find(d => d.id === data.document_id) || {}).url,
      },
    }
    // 保存済みの回答を復元
    if (data.user_answers && typeof data.user_answers === 'object') {
      quizStore.userAnswers = { ...data.user_answers }
      Object.keys(data.user_answers).forEach((qid) => {
        quizStore.revealed[qid] = true
      })
    }
  } catch (e) {
    console.warn('保存済みセッション読み込みエラー:', e)
  }
}

async function refreshDocuments() {
  documentsLoading.value = true
  try {
    await docsStore.fetchDocuments()
    documents.value = docsStore.documents
  } catch (_) {}
  documentsLoading.value = false
}

function truncateUrl(url) {
  if (!url) return ''
  if (url.length <= 40) return url
  return url.substring(0, 37) + '...'
}

function formatDate(iso) {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString('ja-JP', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    })
  } catch (_) { return '-' }
}

function difficultyLabel(d) {
  return { easy: '易', medium: '普', hard: '難' }[d] || d
}

function scoreColorClass(correct, total) {
  if (!total) return ''
  const pct = (correct / total) * 100
  if (pct >= 70) return 'score-high'
  if (pct >= 40) return 'score-mid'
  return 'score-low'
}

function increaseDepth() {
  if (params.value.depth < 8) params.value.depth++
}
function decreaseDepth() {
  if (params.value.depth > 1) params.value.depth--
}

async function previewContent() {
  if (!params.value.source) return
  previewing.value   = true
  preview.value      = null
  previewError.value = null
  try {
    const res = await api.post('/content/preview', {
      source:    params.value.source,
      depth:     params.value.depth,
      doc_types: params.value.doc_types,
    })
    preview.value = res.data
  } catch (e) {
    previewError.value = e.response?.data?.error || e.message
  } finally {
    previewing.value = false
  }
}

async function generate() {
  currentStep.value = 0
  if (isUrl.value && params.value.depth >= 1) {
    scrapeStore.startScrape(params.value.source, params.value.depth, params.value.doc_types)
  } else {
    // テキスト入力の場合はスクレイピングをスキップ
    currentStep.value = 2
  }
  await quizStore.generate({ ...params.value })
}

function formatSize(bytes) {
  if (!bytes) return ''
  const gb = bytes / 1024 ** 3
  return gb >= 1 ? `${gb.toFixed(1)}GB` : `${(bytes / 1024 ** 2).toFixed(0)}MB`
}

// Handle prefilled source from route query
onMounted(() => {
  modelsStore.fetchModels()
  refreshDocuments()

  if (route.query.source) {
    params.value.source = route.query.source
  }
})

// Watch for route query changes
watch(() => route.query.source, (newSource) => {
  if (newSource) {
    params.value.source = newSource
  }
})

// ---- 既取得URL検出 ----
function formatScrapedAt(iso) {
  if (!iso) return '-'
  try {
    const d = new Date(iso)
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    return `${y}/${m}/${day} ${hh}:${mm}`
  } catch (_) { return '-' }
}

async function checkExistingUrl(url) {
  try {
    const res = await api.get('/documents/by-url', { params: { url } })
    existingDocument.value = res.data
  } catch (_) {
    existingDocument.value = null
  }
}

function useExistingDocument() {
  if (!existingDocument.value) return
  // selectDocument は params.source を上書きするため、以後の再検知を抑止する
  suppressedUrl = (existingDocument.value.url || '').trim()
  selectDocument(existingDocument.value)
  existingDocument.value = null
}

function dismissExistingDocument() {
  // 同一URLのままなら再表示しないよう抑止URLに登録
  suppressedUrl = (params.value.source || '').trim()
  existingDocument.value = null
}

// params.source を600msデバウンスで監視
watch(() => params.value.source, (newVal) => {
  if (existingDocumentTimer) {
    clearTimeout(existingDocumentTimer)
    existingDocumentTimer = null
  }
  const src = (newVal || '').trim()
  // URL形式でない、または短すぎる場合は通知をクリア
  if (!/^https?:\/\//.test(src) || src.length <= 8) {
    existingDocument.value = null
    return
  }
  // 抑止URLと一致するなら検知しない。URLが変わった時点で抑止を解除する。
  if (suppressedUrl && src === suppressedUrl) {
    return
  }
  suppressedUrl = null
  existingDocumentTimer = setTimeout(() => {
    checkExistingUrl(src)
  }, 600)
})
</script>

<style scoped>
.generate-page {
  display: flex;
  gap: 0;
  min-height: calc(100vh - 60px);
  position: relative;
}

/* ========== サイドバー ========== */
.sidebar {
  width: 220px;
  flex-shrink: 0;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.2s;
  position: sticky;
  top: 60px;
  align-self: flex-start;
  height: calc(100vh - 60px);
}
.sidebar.collapsed {
  width: 48px;
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.sidebar-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
}
.sidebar-toggle {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 10px;
  padding: 4px;
  border-radius: 4px;
  flex-shrink: 0;
}
.sidebar-toggle:hover { color: var(--text-primary); background: rgba(255,255,255,0.05); }

.btn-icon {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 14px;
  padding: 2px 4px;
  border-radius: 4px;
  flex-shrink: 0;
}
.btn-icon:hover { color: var(--text-primary); }
.btn-icon:disabled { opacity: 0.4; }

.sidebar-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.sidebar-empty {
  padding: 20px 12px;
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
}

.sidebar-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  transition: background 0.15s;
  border-left: 3px solid transparent;
}
.sidebar-item:hover { background: rgba(255,255,255,0.03); }
.sidebar-item.active {
  background: rgba(99,102,241,0.1);
  border-left-color: var(--accent);
}

.sidebar-item-icon { font-size: 14px; flex-shrink: 0; }
.sidebar-item-text {
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.sidebar-list-collapsed {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}
.sidebar-item-icon-only {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px 0;
  cursor: pointer;
  font-size: 16px;
  border-left: 3px solid transparent;
  transition: background 0.15s;
}
.sidebar-item-icon-only:hover { background: rgba(255,255,255,0.03); }
.sidebar-item-icon-only.active {
  background: rgba(99,102,241,0.1);
  border-left-color: var(--accent);
}

/* ========== 中央カラム ========== */
.center-column {
  flex: 1;
  min-width: 0;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow-y: auto;
}

.section-title { font-size: 16px; font-weight: 700; margin-bottom: 16px; }

.config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.full-width { grid-column: 1 / -1; }

.source-input-row { display: flex; gap: 8px; }
.source-input-row .form-input { flex: 1; }

/* ---- 既取得URL通知 ---- */
.already-scraped-notice {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.already-scraped-title {
  font-weight: 700;
  font-size: 13px;
}
.already-scraped-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 12px;
  opacity: 0.9;
}
.already-scraped-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 4px;
}
.already-scraped-actions .btn {
  font-size: 12px;
  padding: 6px 12px;
}

/* ---- スクレイピングオプション ---- */
.scrape-options {
  margin-top: 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
}
.scrape-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.form-label-sm {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.field-hint { font-size: 11px; color: var(--text-muted); margin-top: 6px; }

/* 階層数コントロール */
.depth-control {
  display: flex;
  align-items: center;
  gap: 8px;
}
.depth-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s;
}
.depth-btn:hover:not(:disabled) { background: var(--accent); color: #fff; }
.depth-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.depth-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--accent-hover);
  min-width: 28px;
  text-align: center;
}
.depth-hint { font-size: 12px; color: var(--text-muted); }

/* ドキュメント種別 */
.doc-type-group { display: flex; gap: 8px; flex-wrap: wrap; }
.doc-type-label {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg-secondary);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.15s;
  user-select: none;
}
.doc-type-label input { display: none; }
.doc-type-label.active {
  border-color: var(--accent);
  background: rgba(99,102,241,0.15);
  color: var(--accent-hover);
}
.doc-type-icon { font-size: 14px; }

/* プレビュー */
.preview-box {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-top: 8px;
}
.preview-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }
.preview-title  { font-weight: 600; font-size: 13px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.preview-text   { font-size: 12px; color: var(--text-muted); line-height: 1.5; margin-top: 6px; }

.doc-types-found { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.doc-types-label { font-size: 11px; color: var(--text-muted); }
.doc-type-badge {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 4px;
  background: rgba(99,102,241,0.15);
  color: var(--accent-hover);
}

.pages-detail { margin: 6px 0; font-size: 12px; }
.pages-detail summary { cursor: pointer; color: var(--text-muted); }
.pages-list { list-style: none; padding: 6px 0 0 0; display: flex; flex-direction: column; gap: 3px; max-height: 120px; overflow-y: auto; }
.pages-list li { display: flex; align-items: center; gap: 6px; }
.page-depth {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--bg-secondary);
  color: var(--text-muted);
  white-space: nowrap;
}
.pages-list a { font-size: 11px; color: var(--accent); text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pages-list a:hover { text-decoration: underline; }

.model-row { display: flex; gap: 8px; }
.model-row .form-select { flex: 1; }

.checkbox-group { display: flex; gap: 12px; flex-wrap: wrap; }
.checkbox-label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.checkbox-label input { accent-color: var(--accent); }

.radio-group { display: flex; gap: 16px; }
.radio-label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.radio-label input { accent-color: var(--accent); }

.generate-actions { display: flex; gap: 12px; margin-top: 20px; }
.generate-btn { padding: 10px 28px; font-size: 14px; }

/* ========== 保存済み問題セット ========== */
.saved-sessions-panel { padding: 16px 20px; }
.saved-sessions-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.saved-sessions-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  flex: 1;
}
.saved-count {
  font-size: 11px;
  color: var(--text-muted);
  padding: 2px 8px;
  background: var(--bg-primary);
  border-radius: 10px;
}
.saved-sessions-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 240px;
  overflow-y: auto;
}
.saved-session-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-primary);
  cursor: pointer;
  text-align: left;
  color: var(--text-primary);
  transition: all 0.15s;
}
.saved-session-item:hover {
  border-color: var(--accent);
  background: rgba(99,102,241,0.05);
}
.saved-session-item.active {
  border-color: var(--accent);
  background: rgba(99,102,241,0.12);
}
.saved-session-main {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
}
.saved-session-meta { color: var(--text-muted); }
.saved-session-model {
  color: var(--accent-hover);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 180px;
  white-space: nowrap;
}
.saved-session-count { color: var(--text-muted); }
.saved-session-diff {
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
}
.diff-easy   { background: rgba(34,197,94,0.15);  color: var(--success); }
.diff-medium { background: rgba(251,191,36,0.15); color: #fbbf24; }
.diff-hard   { background: rgba(239,68,68,0.15);  color: var(--danger); }

.saved-session-score {
  font-size: 12px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 6px;
  white-space: nowrap;
  flex-shrink: 0;
}
.saved-session-score.score-high { background: rgba(34,197,94,0.15);  color: var(--success); }
.saved-session-score.score-mid  { background: rgba(251,191,36,0.15); color: #fbbf24; }
.saved-session-score.score-low  { background: rgba(239,68,68,0.15);  color: var(--danger); }
.saved-session-score.pending    { background: var(--border);         color: var(--text-muted); }

/* ========== ステップインジケーター ========== */
.generating-steps { padding: 20px; }
.steps-row {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: center;
}
.step {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 13px;
  border: 1px solid var(--border);
  background: var(--bg-primary);
  transition: all 0.3s;
  white-space: nowrap;
}
.step.active {
  border-color: var(--accent);
  background: rgba(99,102,241,0.15);
  color: var(--accent-hover);
  font-weight: 600;
}
.step.done {
  border-color: rgba(34,197,94,0.3);
  background: rgba(34,197,94,0.08);
  color: var(--success);
}
.step.pending { opacity: 0.4; }
.step-num { font-size: 14px; }
.step-label { font-size: 12px; }
.step-icon { display: flex; align-items: center; }
.step-arrow { color: var(--text-muted); font-size: 14px; flex-shrink: 0; padding: 0 2px; }
.steps-detail {
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 12px;
}

/* ========== 生成プログレスバー ========== */
.gen-progress {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
}
.gen-progress-bar {
  flex: 1;
  height: 6px;
  background: var(--bg-primary);
  border-radius: 3px;
  overflow: hidden;
}
.gen-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent-hover));
  border-radius: 3px;
  transition: width 0.4s ease;
}
.gen-progress-text {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
  flex-shrink: 0;
}

/* ========== 問題リスト追加アニメーション ========== */
.questions-list { display: flex; flex-direction: column; gap: 16px; }
.question-fade-enter-active { animation: fadeSlideIn 0.4s ease-out; }
@keyframes fadeSlideIn {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}

.result-section { display: flex; flex-direction: column; gap: 16px; }

.score-card {
  text-align: center;
  padding: 32px;
  background: linear-gradient(135deg, rgba(99,102,241,0.15), rgba(99,102,241,0.05));
  border-color: rgba(99,102,241,0.4);
}
.score-display { display: flex; align-items: baseline; justify-content: center; gap: 4px; }
.score-num   { font-size: 56px; font-weight: 800; color: var(--accent-hover); }
.score-sep   { font-size: 32px; color: var(--text-muted); }
.score-total { font-size: 32px; color: var(--text-muted); }
.score-label { color: var(--text-muted); font-size: 13px; margin-top: 4px; }
.score-pct   { font-size: 24px; font-weight: 700; color: var(--success); margin-top: 8px; }

.result-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-muted);
  padding: 0 4px;
}

/* ========== 右パネル ========== */
.progress-panel {
  width: 280px;
  flex-shrink: 0;
  background: var(--bg-secondary);
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: sticky;
  top: 60px;
  align-self: flex-start;
  height: calc(100vh - 60px);
}

.progress-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.progress-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.mobile-close-btn {
  display: none;
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 14px;
}

.progress-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.progress-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 10px;
}

.progress-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.progress-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 4px;
  font-size: 11px;
  transition: background 0.15s;
}
.progress-item.done { opacity: 0.7; }
.progress-item.error { background: rgba(239,68,68,0.1); }

.progress-depth {
  font-size: 9px;
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--bg-primary);
  color: var(--text-muted);
  white-space: nowrap;
  flex-shrink: 0;
}
.progress-url {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
}
.progress-status {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

.progress-idle {
  padding: 24px 12px;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
}

/* ========== モバイルボタン ========== */
.mobile-sidebar-btn,
.mobile-progress-btn {
  display: none;
  position: fixed;
  z-index: 50;
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
  align-items: center;
  gap: 6px;
}
.mobile-sidebar-btn { bottom: 16px; left: 16px; }
.mobile-progress-btn { bottom: 16px; right: 16px; }

.mobile-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.5);
  z-index: 59;
}

/* ========== レスポンシブ ========== */

/* タブレット: サイドバー縮小、右パネル幅縮小 */
@media (max-width: 1200px) {
  .progress-panel { width: 220px; }
}

@media (max-width: 1024px) {
  .sidebar:not(.mobile-open) {
    width: 48px;
  }
  .sidebar:not(.mobile-open) .sidebar-title,
  .sidebar:not(.mobile-open) .sidebar-list,
  .sidebar:not(.mobile-open) .btn-icon {
    display: none;
  }
  .sidebar:not(.mobile-open) .sidebar-list-collapsed {
    display: flex;
    flex-direction: column;
  }
  .sidebar.collapsed .sidebar-list-collapsed {
    display: flex;
    flex-direction: column;
  }
  .progress-panel { width: 200px; }
  .center-column { padding: 16px; }
  .config-grid { grid-template-columns: 1fr; }
  .scrape-row  { grid-template-columns: 1fr; }
  .steps-row { gap: 2px; }
  .step { padding: 6px 8px; font-size: 12px; }
  .step-label { font-size: 11px; }
}

/* モバイル: サイドバーとパネルはオーバーレイ */
@media (max-width: 768px) {
  .generate-page {
    flex-direction: column;
  }

  .sidebar {
    display: none;
    position: fixed;
    top: 52px;
    left: 0;
    bottom: 0;
    width: 260px;
    z-index: 60;
  }
  .sidebar.mobile-open {
    display: flex;
    width: 260px;
  }
  .sidebar.mobile-open .sidebar-list { display: block; }
  .sidebar.mobile-open .sidebar-list-collapsed { display: none; }
  .sidebar.mobile-open .sidebar-title { display: block; }
  .sidebar.mobile-open .btn-icon { display: inline-flex; }

  .progress-panel {
    display: none;
    position: fixed;
    top: 52px;
    right: 0;
    bottom: 0;
    width: 280px;
    z-index: 60;
  }
  .progress-panel.mobile-open {
    display: flex;
  }
  .progress-panel.mobile-open .mobile-close-btn {
    display: inline-block;
  }

  .mobile-sidebar-btn,
  .mobile-progress-btn {
    display: flex;
  }
  .mobile-overlay {
    display: block;
  }

  .center-column {
    padding: 12px;
  }

  .source-input-row { flex-direction: column; }
  .model-row { flex-direction: column; }
  .model-row .form-select { width: 100%; }
  .generate-actions { flex-direction: column; }
  .generate-btn { width: 100%; justify-content: center; }

  .radio-group { flex-direction: column; gap: 8px; }

  .result-meta { flex-direction: column; gap: 8px; align-items: flex-start; }
  .result-meta button { margin-left: 0; width: 100%; justify-content: center; }

  .score-num   { font-size: 40px; }
  .score-total { font-size: 24px; }
  .score-sep   { font-size: 24px; }
  .score-pct   { font-size: 20px; }
  .score-card  { padding: 20px; }

  /* ステップ: 縦並び */
  .steps-row { flex-direction: column; align-items: stretch; gap: 4px; }
  .step-arrow { display: none; }
  .step { justify-content: space-between; }
}

/* 小画面 */
@media (max-width: 480px) {
  .center-column { padding: 8px; }
  .card { padding: 14px; }
  .section-title { font-size: 14px; }
  .doc-type-group { gap: 4px; }
  .doc-type-label { padding: 4px 8px; font-size: 11px; }
  .checkbox-group { gap: 8px; }
}
</style>
