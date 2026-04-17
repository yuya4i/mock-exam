<template>
  <div class="results-page">
    <!-- ヘッダー -->
    <div class="page-header">
      <h2 class="section-title">分析</h2>
      <span class="total-count">{{ resultsStore.totalSessions }} セッション</span>
      <button class="btn btn-secondary" @click="resultsStore.fetchResults({ force: true })" :disabled="resultsStore.loading" style="margin-left:auto">
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

      <!-- 弱点推奨パネル -->
      <div v-if="weakPoints.length > 0" class="card weak-points-panel">
        <div class="weak-points-header">
          <span class="weak-points-icon">🎯</span>
          <h3 class="card-title" style="margin:0">強化推奨エリア</h3>
          <span class="weak-points-hint">正答率が低い分野から優先的に復習しましょう</span>
        </div>
        <div class="weak-points-list">
          <div
            v-for="wp in weakPoints"
            :key="`${wp.category}-${wp.level || wp.label}`"
            class="weak-point-item"
            :class="`priority-${wp.priority}`"
          >
            <span class="wp-priority">{{ priorityLabel(wp.priority) }}</span>
            <span class="wp-category">{{ wp.category }}</span>
            <span class="wp-detail">{{ wp.label }}</span>
            <span class="wp-score" :class="scoreColor(wp.accuracy)">
              {{ wp.correct }}/{{ wp.total }}問 ({{ wp.accuracy }}%)
            </span>
          </div>
        </div>
      </div>

      <!-- カテゴリ別正答率レーダー（全カテゴリ比較） -->
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

      <!-- 各カテゴリ別レーダーチャート（K1-K4・難易度・トピック） -->
      <div v-if="resultsStore.breakdown.length > 0" class="per-category-section">
        <h3 class="sub-title">カテゴリ別詳細分析</h3>
        <div class="per-cat-grid">
          <div
            v-for="cat in resultsStore.breakdown"
            :key="cat.category"
            class="card per-cat-card"
          >
            <div class="per-cat-header" @click="toggleCategory(cat.category)">
              <span class="per-cat-name">{{ cat.category }}</span>
              <span class="per-cat-total" :class="scoreColor(cat.total.accuracy)">
                {{ cat.total.accuracy }}% ({{ cat.total.correct }}/{{ cat.total.total }})
              </span>
              <span class="expand-icon">{{ expandedCats[cat.category] ? '▼' : '▶' }}</span>
            </div>
            <div v-if="expandedCats[cat.category]" class="per-cat-body">
              <!-- 知識レベル レーダー -->
              <div class="per-cat-chart">
                <div class="per-cat-chart-title">知識レベル別（K1〜K4）</div>
                <div class="per-cat-radar-container">
                  <Radar :data="levelRadarData(cat)" :options="smallRadarOptions" />
                </div>
              </div>
              <!-- 難易度 レーダー -->
              <div class="per-cat-chart" v-if="hasDifficultyData(cat)">
                <div class="per-cat-chart-title">難易度別</div>
                <div class="per-cat-radar-container">
                  <Radar :data="difficultyRadarData(cat)" :options="smallRadarOptions" />
                </div>
              </div>
              <!-- トピック別 -->
              <div class="per-cat-chart full-span" v-if="cat.topics.length > 1">
                <div class="per-cat-chart-title">トピック別正答率（上位 {{ cat.topics.length }}）</div>
                <div class="topic-bars">
                  <div v-for="t in cat.topics" :key="t.topic" class="topic-bar">
                    <span class="topic-bar-label" :title="t.topic">{{ t.topic }}</span>
                    <div class="topic-bar-track">
                      <div
                        class="topic-bar-fill"
                        :class="scoreColor(t.accuracy)"
                        :style="{ width: `${t.accuracy}%` }"
                      ></div>
                    </div>
                    <span class="topic-bar-score">{{ t.correct }}/{{ t.total }}</span>
                  </div>
                </div>
              </div>
            </div>
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
                :source-info="sessionDetails[session.session_id].source_info"
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
const expandedCats     = reactive({})
const sessionDetails   = reactive({})
const deleteTarget     = ref(null)
const deleting         = ref(false)

// 弱点閾値（正答率がこれ未満なら強化推奨）
const WEAK_THRESHOLD     = 60
const MIN_QUESTIONS_FOR_WEAK = 3  // 最低この問題数が必要

function toggleCategory(cat) {
  expandedCats[cat] = !expandedCats[cat]
}

// レーダー色のパレット（カテゴリごとに色を割り当て）
const RADAR_COLORS = [
  { bg: 'rgba(99, 102, 241, 0.2)',  border: 'rgba(99, 102, 241, 0.9)'  },
  { bg: 'rgba(34, 197, 94, 0.2)',   border: 'rgba(34, 197, 94, 0.9)'   },
  { bg: 'rgba(251, 191, 36, 0.2)',  border: 'rgba(251, 191, 36, 0.9)'  },
  { bg: 'rgba(239, 68, 68, 0.2)',   border: 'rgba(239, 68, 68, 0.9)'   },
  { bg: 'rgba(168, 85, 247, 0.2)',  border: 'rgba(168, 85, 247, 0.9)'  },
]

function colorFor(cat) {
  const idx = resultsStore.breakdown.findIndex((c) => c.category === cat.category)
  return RADAR_COLORS[idx % RADAR_COLORS.length]
}

function levelRadarData(cat) {
  const c = colorFor(cat)
  const levels = ['K1', 'K2', 'K3', 'K4']
  return {
    labels: levels,
    datasets: [{
      label: `${cat.category} 正答率`,
      data:  levels.map((lv) => cat.levels[lv]?.accuracy || 0),
      backgroundColor: c.bg,
      borderColor:     c.border,
      borderWidth: 2,
      pointBackgroundColor: c.border,
      pointBorderColor: '#fff',
      pointRadius: 3,
    }],
  }
}

function difficultyRadarData(cat) {
  const c = colorFor(cat)
  const diffs = [
    { key: 'easy',   label: '易' },
    { key: 'medium', label: '普' },
    { key: 'hard',   label: '難' },
  ]
  return {
    labels: diffs.map((d) => d.label),
    datasets: [{
      label: '正答率',
      data:  diffs.map((d) => cat.difficulties[d.key]?.accuracy || 0),
      backgroundColor: c.bg,
      borderColor:     c.border,
      borderWidth: 2,
      pointBackgroundColor: c.border,
      pointBorderColor: '#fff',
      pointRadius: 3,
    }],
  }
}

function hasDifficultyData(cat) {
  return Object.values(cat.difficulties).some((d) => d.total > 0)
}

const smallRadarOptions = {
  responsive: true,
  maintainAspectRatio: false,
  scales: {
    r: {
      min: 0, max: 100,
      ticks: { stepSize: 25, color: '#94a3b8', backdropColor: 'transparent', font: { size: 10 } },
      grid:       { color: 'rgba(51, 65, 85, 0.5)' },
      angleLines: { color: 'rgba(51, 65, 85, 0.5)' },
      pointLabels:{ color: '#f1f5f9', font: { size: 11, weight: '600' } },
    },
  },
  plugins: {
    legend: { display: false },
    tooltip: { callbacks: { label: (ctx) => `${ctx.raw}%` } },
  },
}

// 弱点ポイント抽出（カテゴリ×知識レベル で正答率が閾値未満のものをピックアップ）
const weakPoints = computed(() => {
  const items = []
  for (const cat of resultsStore.breakdown) {
    // カテゴリ全体が低い場合
    if (cat.total.total >= MIN_QUESTIONS_FOR_WEAK && cat.total.accuracy < WEAK_THRESHOLD) {
      items.push({
        category: cat.category,
        label:    '全体',
        correct:  cat.total.correct,
        total:    cat.total.total,
        accuracy: cat.total.accuracy,
        priority: cat.total.accuracy < 40 ? 'high' : 'mid',
      })
    }
    // 特定のK-levelが低い場合
    for (const lv of ['K1', 'K2', 'K3', 'K4']) {
      const b = cat.levels[lv]
      if (b.total >= MIN_QUESTIONS_FOR_WEAK && b.accuracy < WEAK_THRESHOLD) {
        items.push({
          category: cat.category,
          label:    `${lv}`,
          level:    lv,
          correct:  b.correct,
          total:    b.total,
          accuracy: b.accuracy,
          priority: b.accuracy < 40 ? 'high' : 'low',
        })
      }
    }
  }
  // 正答率昇順（最も弱い順）、最大8件
  return items.sort((a, b) => a.accuracy - b.accuracy).slice(0, 8)
})

function priorityLabel(p) {
  return { high: '最優先', mid: '要注意', low: '改善推奨' }[p] || p
}

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
  // Force-fetch when entering the analytics page so the user sees a
  // fresh snapshot even if the per-save throttle is "still cooling".
  resultsStore.fetchResults({ force: true })
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

/* ========== 弱点推奨 ========== */
.weak-points-panel { padding: 18px 20px; }
.weak-points-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.weak-points-icon { font-size: 20px; }
.weak-points-hint { font-size: 11px; color: var(--text-muted); margin-left: auto; }

.weak-points-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.weak-point-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--bg-primary);
  border-left: 3px solid var(--border);
  font-size: 12px;
}
.weak-point-item.priority-high { border-left-color: var(--danger);  background: rgba(239,68,68,0.06); }
.weak-point-item.priority-mid  { border-left-color: var(--warning); background: rgba(251,191,36,0.06); }
.weak-point-item.priority-low  { border-left-color: var(--accent);  background: rgba(99,102,241,0.04); }

.wp-priority {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 10px;
  white-space: nowrap;
  flex-shrink: 0;
}
.priority-high .wp-priority { background: rgba(239,68,68,0.2);  color: var(--danger); }
.priority-mid .wp-priority  { background: rgba(251,191,36,0.2); color: var(--warning); }
.priority-low .wp-priority  { background: rgba(99,102,241,0.2); color: var(--accent-hover); }

.wp-category {
  font-weight: 600;
  color: var(--text-primary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-detail {
  color: var(--text-muted);
  font-size: 11px;
  padding: 2px 6px;
  background: var(--bg-secondary);
  border-radius: 4px;
  flex-shrink: 0;
}
.wp-score {
  font-weight: 700;
  font-size: 12px;
  flex-shrink: 0;
}

/* ========== カテゴリ別詳細 ========== */
.per-category-section { display: flex; flex-direction: column; gap: 10px; }

.per-cat-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}

.per-cat-card { padding: 0; overflow: hidden; }

.per-cat-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  cursor: pointer;
  transition: background 0.15s;
}
.per-cat-header:hover { background: rgba(255,255,255,0.02); }

.per-cat-name {
  font-weight: 600;
  font-size: 14px;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.per-cat-total {
  font-weight: 700;
  font-size: 13px;
  padding: 4px 10px;
  border-radius: 6px;
  background: var(--bg-primary);
}

.per-cat-body {
  border-top: 1px solid var(--border);
  padding: 18px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.per-cat-chart.full-span { grid-column: 1 / -1; }

.per-cat-chart-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 10px;
  text-align: center;
}
.per-cat-radar-container {
  position: relative;
  height: 220px;
  max-width: 280px;
  margin: 0 auto;
}

/* トピック別バー */
.topic-bars { display: flex; flex-direction: column; gap: 6px; }
.topic-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.topic-bar-label {
  flex-basis: 180px;
  flex-shrink: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
}
.topic-bar-track {
  flex: 1;
  height: 10px;
  background: var(--bg-primary);
  border-radius: 5px;
  overflow: hidden;
}
.topic-bar-fill {
  height: 100%;
  transition: width 0.3s;
}
.topic-bar-fill.score-green  { background: var(--success); }
.topic-bar-fill.score-yellow { background: var(--warning); }
.topic-bar-fill.score-red    { background: var(--danger); }
.topic-bar-score {
  font-size: 11px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
  min-width: 50px;
  text-align: right;
}

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
  .per-cat-body { grid-template-columns: 1fr; gap: 14px; }
  .per-cat-radar-container { height: 200px; }
  .topic-bar-label { flex-basis: 120px; font-size: 11px; }
  .weak-point-item { flex-wrap: wrap; }
  .wp-detail { order: 3; }
}
</style>
