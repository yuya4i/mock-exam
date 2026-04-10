<template>
  <div class="results-page">
    <!-- ヘッダー -->
    <div class="page-header">
      <h2 class="section-title">分析</h2>
      <span class="total-count">{{ resultsStore.totalSessions }} セッション</span>
      <button class="btn btn-secondary" @click="resultsStore.fetchResults()" :disabled="resultsStore.loading" style="margin-left:auto">
        <span v-if="resultsStore.loading" class="spinner"></span>
        <span v-else>更新</span>
      </button>
    </div>

    <!-- ローディング -->
    <div v-if="resultsStore.loading" class="loading-state">
      <div class="spinner" style="width:32px;height:32px;border-width:3px"></div>
      <span>読み込み中...</span>
    </div>

    <!-- エラー -->
    <div v-else-if="resultsStore.error" class="alert alert-error">
      {{ resultsStore.error }}
    </div>

    <!-- 空状態 -->
    <div v-else-if="resultsStore.sessions.length === 0" class="empty-state card">
      <span style="font-size:48px">📊</span>
      <p>まだ分析データがありません。</p>
      <RouterLink to="/" class="btn btn-primary">問題を生成する</RouterLink>
    </div>

    <!-- メインコンテンツ -->
    <template v-else>
      <!-- 統計サマリー -->
      <div class="stats-row">
        <div class="stat-card card">
          <div class="stat-value">{{ resultsStore.totalSessions }}</div>
          <div class="stat-label">セッション数</div>
        </div>
        <div class="stat-card card">
          <div class="stat-value" :class="scoreColor(resultsStore.averageScore)">{{ resultsStore.averageScore }}%</div>
          <div class="stat-label">平均正答率</div>
        </div>
        <div class="stat-card card">
          <div class="stat-value">{{ resultsStore.totalQuestions }}</div>
          <div class="stat-label">総問題数</div>
        </div>
        <div class="stat-card card">
          <div class="stat-value">{{ resultsStore.categories.length }}</div>
          <div class="stat-label">カテゴリ数</div>
        </div>
      </div>

      <!-- レーダーチャート -->
      <div v-if="radarData" class="card radar-section">
        <h3 class="card-title">カテゴリ別正答率</h3>
        <div class="radar-container">
          <Radar :data="radarData" :options="radarOptions" />
        </div>
        <div class="category-legend">
          <div
            v-for="cat in resultsStore.categories"
            :key="cat.category"
            class="legend-item"
          >
            <span class="legend-name">{{ cat.category }}</span>
            <span class="legend-stats">
              {{ cat.total_correct }}/{{ cat.total_answered }}問
              <span :class="scoreColor(cat.accuracy)">({{ cat.accuracy }}%)</span>
            </span>
          </div>
        </div>
      </div>

      <!-- セッション一覧 -->
      <h3 class="sub-title">正誤履歴</h3>

      <!-- フィルター -->
      <div class="filter-row">
        <select v-model="filterCategory" class="form-select" style="max-width:300px">
          <option value="">全てのカテゴリ</option>
          <option v-for="cat in uniqueCategories" :key="cat" :value="cat">{{ cat }}</option>
        </select>
      </div>

      <div class="sessions-list">
        <div
          v-for="session in filteredSessions"
          :key="session.session_id"
          class="session-card card"
        >
          <div class="session-header" @click="toggleSession(session.session_id)">
            <div class="session-info">
              <span class="session-title">{{ session.source_title || '不明' }}</span>
              <div class="session-badges">
                <span v-if="session.category" class="badge badge-k1">{{ session.category }}</span>
                <span class="badge badge-k2">{{ session.question_count }}問</span>
                <span class="badge badge-k3">{{ difficultyLabel(session.difficulty) }}</span>
              </div>
            </div>
            <div class="session-score" v-if="session.score_total > 0">
              <span class="score-fraction">{{ session.score_correct }}/{{ session.score_total }}</span>
              <span :class="['score-pct', scoreColor(scorePct(session))]">
                {{ scorePct(session) }}%
              </span>
            </div>
            <div class="session-score" v-else>
              <span class="score-pending">未回答</span>
            </div>
            <div class="session-meta">
              <span v-if="session.generated_at">生成: {{ formatDate(session.generated_at) }}</span>
              <span v-if="session.answered_at">回答: {{ formatDate(session.answered_at) }}</span>
            </div>
            <div class="session-actions">
              <button class="btn btn-danger btn-sm" @click.stop="confirmDelete(session)">削除</button>
              <span class="expand-icon">{{ expandedSessions[session.session_id] ? '▼' : '▶' }}</span>
            </div>
          </div>

          <!-- 展開した問題一覧 -->
          <div v-if="expandedSessions[session.session_id]" class="session-detail">
            <div v-if="sessionDetails[session.session_id] === 'loading'" class="loading-state" style="padding:20px">
              <div class="spinner"></div>
              <span>読み込み中...</span>
            </div>
            <div v-else-if="sessionDetails[session.session_id]" class="detail-questions">
              <QuestionCard
                v-for="(q, i) in sessionDetails[session.session_id].questions"
                :key="q.id"
                :question="q"
                :index="i"
                :user-answer="q.user_answer || null"
                :revealed="!!q.user_answer"
              />
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 削除確認ダイアログ -->
    <div v-if="deleteTarget" class="modal-overlay" @click.self="deleteTarget = null">
      <div class="modal-content modal-sm">
        <div class="modal-header">
          <h3>セッションを削除</h3>
        </div>
        <p class="confirm-text">
          「{{ deleteTarget.source_title || '不明' }}」のセッションを削除しますか？
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
import { ref, computed, reactive, onMounted } from 'vue'
import { useResultsStore } from '@/stores'
import QuestionCard from '@/components/QuestionCard.vue'
import { Radar } from 'vue-chartjs'
import {
  Chart as ChartJS,
  RadialLinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
} from 'chart.js'

ChartJS.register(RadialLinearScale, PointElement, LineElement, Filler, Tooltip, Legend)

const resultsStore = useResultsStore()

const filterCategory   = ref('')
const expandedSessions = reactive({})
const sessionDetails   = reactive({})
const deleteTarget     = ref(null)
const deleting         = ref(false)

// ---- レーダーチャート ----
const radarData = computed(() => {
  const cats = resultsStore.categories
  if (!cats.length) return null

  return {
    labels: cats.map((c) => c.category),
    datasets: [
      {
        label: '正答率 (%)',
        data: cats.map((c) => c.accuracy),
        backgroundColor: 'rgba(99, 102, 241, 0.2)',
        borderColor: 'rgba(99, 102, 241, 0.8)',
        borderWidth: 2,
        pointBackgroundColor: 'rgba(99, 102, 241, 1)',
        pointBorderColor: '#fff',
        pointRadius: 4,
        pointHoverRadius: 6,
      },
      {
        label: '出題数',
        data: cats.map((c) => Math.min(c.total_answered, 100)),
        backgroundColor: 'rgba(34, 197, 94, 0.1)',
        borderColor: 'rgba(34, 197, 94, 0.5)',
        borderWidth: 1,
        borderDash: [4, 4],
        pointRadius: 2,
        hidden: true,
      },
    ],
  }
})

const radarOptions = {
  responsive: true,
  maintainAspectRatio: false,
  scales: {
    r: {
      min: 0,
      max: 100,
      ticks: {
        stepSize: 20,
        color: '#94a3b8',
        backdropColor: 'transparent',
        font: { size: 11 },
      },
      grid: {
        color: 'rgba(51, 65, 85, 0.5)',
      },
      angleLines: {
        color: 'rgba(51, 65, 85, 0.5)',
      },
      pointLabels: {
        color: '#f1f5f9',
        font: { size: 12, weight: '600' },
      },
    },
  },
  plugins: {
    legend: {
      display: true,
      labels: { color: '#94a3b8', font: { size: 11 } },
    },
    tooltip: {
      callbacks: {
        label: (ctx) => `${ctx.dataset.label}: ${ctx.raw}${ctx.datasetIndex === 0 ? '%' : '問'}`,
      },
    },
  },
}

// ---- フィルター ----
const uniqueCategories = computed(() => {
  const cats = new Set(resultsStore.sessions.map((s) => s.category).filter(Boolean))
  return [...cats]
})

const filteredSessions = computed(() => {
  if (!filterCategory.value) return resultsStore.sessions
  return resultsStore.sessions.filter((s) => s.category === filterCategory.value)
})

// ---- ユーティリティ ----
function scorePct(session) {
  if (!session.score_total) return 0
  return Math.round((session.score_correct / session.score_total) * 100)
}

function scoreColor(pct) {
  if (pct >= 70) return 'score-green'
  if (pct >= 40) return 'score-yellow'
  return 'score-red'
}

function difficultyLabel(d) {
  const map = { easy: '易しい', medium: '普通', hard: '難しい' }
  return map[d] || d || '-'
}

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('ja-JP', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

async function toggleSession(sessionId) {
  if (expandedSessions[sessionId]) {
    expandedSessions[sessionId] = false
    return
  }
  expandedSessions[sessionId] = true
  if (!sessionDetails[sessionId]) {
    sessionDetails[sessionId] = 'loading'
    try {
      const data = await resultsStore.getSession(sessionId)
      sessionDetails[sessionId] = data
    } catch (e) {
      sessionDetails[sessionId] = null
      expandedSessions[sessionId] = false
    }
  }
}

function confirmDelete(session) {
  deleteTarget.value = session
}

async function executeDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await resultsStore.deleteSession(deleteTarget.value.session_id)
    delete expandedSessions[deleteTarget.value.session_id]
    delete sessionDetails[deleteTarget.value.session_id]
    deleteTarget.value = null
  } catch (e) {
    alert('削除に失敗しました: ' + e.message)
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  resultsStore.fetchResults()
})
</script>

<style scoped>
.results-page { display: flex; flex-direction: column; gap: 16px; padding: 24px; max-width: 1400px; margin: 0 auto; width: 100%; }

.page-header { display: flex; align-items: center; gap: 12px; }
.section-title { font-size: 16px; font-weight: 700; }
.total-count { font-size: 12px; color: var(--text-muted); }

.sub-title { font-size: 14px; font-weight: 700; margin-top: 8px; }

/* 統計 */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.stat-card {
  text-align: center;
  padding: 16px;
}
.stat-value {
  font-size: 28px;
  font-weight: 800;
  color: var(--accent-hover);
}
.stat-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}

/* レーダーチャート */
.radar-section {
  padding: 20px;
}
.card-title {
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 16px;
}
.radar-container {
  position: relative;
  height: 360px;
  max-width: 560px;
  margin: 0 auto;
}
.category-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.legend-name {
  font-weight: 600;
  color: var(--text-primary);
}
.legend-stats {
  color: var(--text-muted);
}

.filter-row { display: flex; gap: 12px; }

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

/* セッション一覧 */
.sessions-list { display: flex; flex-direction: column; gap: 10px; }

.session-card { padding: 0; overflow: hidden; }

.session-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  cursor: pointer;
  transition: background 0.15s;
}
.session-header:hover { background: rgba(255,255,255,0.02); }

.session-info { flex: 1; min-width: 0; }
.session-title {
  font-weight: 600;
  font-size: 14px;
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 6px;
}
.session-badges { display: flex; gap: 6px; flex-wrap: wrap; }

.session-score {
  text-align: right;
  flex-shrink: 0;
}
.score-fraction {
  font-size: 16px;
  font-weight: 700;
  display: block;
}
.score-pct {
  font-size: 13px;
  font-weight: 700;
}
.score-pending {
  font-size: 12px;
  color: var(--text-muted);
}

.score-green  { color: var(--success); }
.score-yellow { color: var(--warning); }
.score-red    { color: var(--danger); }

.session-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
  min-width: 130px;
}

.session-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.btn-sm {
  padding: 4px 10px;
  font-size: 11px;
}
.expand-icon {
  font-size: 11px;
  color: var(--text-muted);
  width: 16px;
  text-align: center;
}

/* 展開部分 */
.session-detail {
  border-top: 1px solid var(--border);
  padding: 16px 20px;
}
.detail-questions {
  display: flex;
  flex-direction: column;
  gap: 16px;
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
  max-width: 440px;
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
.modal-header h3 { font-size: 16px; font-weight: 700; }

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

@media (max-width: 768px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
  .session-header { flex-wrap: wrap; }
  .session-meta { min-width: auto; flex-basis: 100%; }
  .radar-container { height: 280px; }
}
</style>
