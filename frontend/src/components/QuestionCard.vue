<template>
  <div
    class="question-card card"
    :class="{ 'revealed': revealed, 'is-regenerating': regenerating }"
  >
    <!-- 自動差し替え中バナー (Mermaid SyntaxError 検知時) -->
    <div v-if="regenerating" class="regen-banner" role="status" aria-live="polite">
      <span class="spinner" style="width:12px;height:12px"></span>
      <span>図のSyntaxエラーを検知。問題を差し替え中…</span>
    </div>

    <!-- ヘッダー -->
    <div class="q-header">
      <span class="q-number">Q{{ index + 1 }}</span>
      <span :class="['badge', `badge-${question.level.toLowerCase()}`]">{{ question.level }}</span>
      <span class="q-topic">{{ question.topic }}</span>
      <span v-if="revealed" :class="['result-badge', isCorrect ? 'correct' : 'incorrect']">
        {{ isCorrect ? '✓ 正解' : '✗ 不正解' }}
      </span>
    </div>

    <!-- 問題文 -->
    <p class="q-text">{{ question.question }}</p>

    <!-- Mermaid図表: SVG が生成できた時だけ表示する (空枠を出さない)。
         レンダ失敗時は親が onDiagramError を受けて単問差し替えるので、
         以前のような raw Mermaid ソースのフォールバックは出さない。 -->
    <div v-if="question.diagram && diagramSvg" class="q-diagram">
      <div v-html="diagramSvg"></div>
    </div>

    <!-- 選択肢 -->
    <div class="choices">
      <button
        v-for="(text, key) in question.choices"
        :key="key"
        class="choice-btn"
        :class="choiceClass(key)"
        @click="!revealed && $emit('answer', key)"
        :disabled="revealed"
      >
        <span class="choice-key">{{ key.toUpperCase() }}</span>
        <span class="choice-text">{{ text }}</span>
        <span v-if="revealed && key === question.answer" class="choice-mark">✓</span>
        <span v-else-if="revealed && key === userAnswer && key !== question.answer" class="choice-mark wrong">✗</span>
      </button>
    </div>

    <!-- アクション -->
    <div class="q-actions" v-if="!revealed">
      <button
        class="btn btn-secondary"
        @click="$emit('reveal')"
        :disabled="!userAnswer"
      >
        解答を確認する
      </button>
      <span v-if="!userAnswer" style="font-size:12px;color:var(--text-muted)">
        選択肢を選んでから確認できます
      </span>
    </div>

    <!-- 解説 -->
    <div v-if="revealed" class="explanation">
      <div class="explanation-header">📖 解説</div>
      <p class="explanation-text">{{ question.explanation }}</p>
      <div v-if="question.source_hint" class="source-hint">
        📌
        <a
          v-if="sourceLink"
          :href="sourceLink"
          target="_blank"
          rel="noopener noreferrer"
          class="source-link"
        >{{ question.source_hint }} から抜粋 ↗</a>
        <span v-else>{{ question.source_hint }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, watch, nextTick } from 'vue'

const props = defineProps({
  question:    { type: Object,  required: true },
  index:       { type: Number,  required: true },
  userAnswer:  { type: String,  default: null  },
  revealed:    { type: Boolean, default: false },
  sourceInfo:  { type: Object,  default: null  },
  // GeneratePage が「Mermaid syntax error → 単問差し替え中」と判断
  // した時に true。カード上部にバナーを出して進行中であることを示す。
  regenerating:{ type: Boolean, default: false },
})

// SEC-12 / FRONTEND-9: defense-in-depth scheme guard. The backend
// already filters non-http(s) URLs out of pages[] in _build_result,
// but a stale cache or manual API call could still hand us one.
function _isSafeHref(url) {
  if (typeof url !== 'string' || !url) return false
  const lower = url.trim().toLowerCase()
  return lower.startsWith('http://') || lower.startsWith('https://')
}

// source_hint のテキストから該当ページURLを検索し、一致しなければソースURLへフォールバック
const sourceLink = computed(() => {
  const info = props.sourceInfo
  const hint = props.question.source_hint
  if (!info || !hint) return ''

  if (Array.isArray(info.pages) && info.pages.length > 0) {
    const lowerHint = hint.toLowerCase()
    const matched = info.pages.find(
      (p) => p.title && lowerHint.includes(p.title.toLowerCase())
    ) || info.pages.find(
      (p) => p.title && p.title.toLowerCase().includes(lowerHint.split(/[・\s]/)[0]?.toLowerCase() || '')
    )
    if (matched?.url && _isSafeHref(matched.url)) return matched.url
  }

  const src = info.source
  if (_isSafeHref(src)) return src
  return ''
})

const emit = defineEmits(['answer', 'reveal', 'diagram-error'])

const diagramSvg = ref('')

// Track whether we already asked the parent to regenerate this card.
// Without this guard a flapping diagram could spam the regenerate
// endpoint on every re-render.
let _regenerateRequested = false

// FRONTEND-10: mermaid.initialize() previously ran INSIDE every
// renderDiagram() call. That config is process-global, so the second
// (and 100th) call re-flushes the SVG cache and re-installs DOMPurify
// hooks for no benefit. Initialize once on first use; subsequent
// renderDiagram() calls just await the same promise.
let _mermaidPromise = null
function _getMermaid() {
  if (!_mermaidPromise) {
    _mermaidPromise = import('mermaid').then(({ default: m }) => {
      // base + themeVariables で全図種のテキストコントラストを明示制御。
      m.initialize({
        startOnLoad: false,
        // SEC-2 defense-in-depth: explicit strict mode (DOMPurify-sanitized
        // SVG, no html labels, no javascript: click handlers).
        securityLevel: 'strict',
        flowchart: { htmlLabels: false },
        theme: 'base',
        fontFamily: "'Segoe UI', 'Hiragino Sans', 'Meiryo', sans-serif",
        themeVariables: {
          background:           '#0f172a',
          primaryColor:         '#1e293b',
          primaryTextColor:     '#f1f5f9',
          primaryBorderColor:   '#6366f1',
          secondaryColor:       '#334155',
          secondaryTextColor:   '#f1f5f9',
          secondaryBorderColor: '#475569',
          tertiaryColor:        '#1e293b',
          tertiaryTextColor:    '#f1f5f9',
          tertiaryBorderColor:  '#334155',
          lineColor:            '#94a3b8',
          textColor:            '#f1f5f9',
          noteBkgColor:         '#3a2a10',
          noteTextColor:        '#fbbf24',
          noteBorderColor:      '#fbbf24',
          actorBkg:             '#1e293b',
          actorBorder:          '#6366f1',
          actorTextColor:       '#f1f5f9',
          actorLineColor:       '#94a3b8',
          signalColor:          '#f1f5f9',
          signalTextColor:      '#f1f5f9',
          labelBoxBkgColor:     '#1e293b',
          labelBoxBorderColor:  '#6366f1',
          labelTextColor:       '#f1f5f9',
          loopTextColor:        '#f1f5f9',
          activationBkgColor:   '#334155',
          activationBorderColor:'#6366f1',
          sequenceNumberColor:  '#0f172a',
          sectionBkgColor:      '#1e293b',
          altSectionBkgColor:   '#0f172a',
          sectionBkgColor2:     '#334155',
          taskBkgColor:         '#6366f1',
          taskTextColor:        '#f1f5f9',
          taskTextLightColor:   '#f1f5f9',
          taskTextOutsideColor: '#f1f5f9',
          taskTextDarkColor:    '#0f172a',
          gridColor:            '#334155',
          todayLineColor:       '#ef4444',
          pie1: '#6366f1', pie2: '#22c55e', pie3: '#fbbf24', pie4: '#ef4444',
          pie5: '#a855f7', pie6: '#06b6d4', pie7: '#f97316', pie8: '#84cc16',
          pie9: '#ec4899', pie10:'#14b8a6', pie11:'#eab308', pie12:'#f43f5e',
          pieTitleTextColor:    '#f1f5f9',
          pieSectionTextColor:  '#0f172a',
          pieLegendTextColor:   '#f1f5f9',
          pieStrokeColor:       '#0f172a',
          pieOuterStrokeColor:  '#475569',
          labelColor:           '#f1f5f9',
          altBackground:        '#0f172a',
          classText:            '#f1f5f9',
          fillType0: '#6366f1', fillType1: '#22c55e', fillType2: '#fbbf24',
          fillType3: '#ef4444', fillType4: '#a855f7', fillType5: '#06b6d4',
          fillType6: '#f97316', fillType7: '#84cc16',
          attributeBackgroundColorOdd:  '#1e293b',
          attributeBackgroundColorEven: '#0f172a',
        },
      })
      return m
    })
  }
  return _mermaidPromise
}

async function renderDiagram() {
  if (!props.question.diagram) return
  // 再レンダ前は前回の SVG を一旦クリアしておく (失敗時に古い SVG が
  // 残らないように)。
  diagramSvg.value = ''
  try {
    const mermaid = await _getMermaid()
    const id = `mermaid-${props.question.id}`
    const { svg } = await mermaid.render(id, props.question.diagram)
    // mermaid.render はサニタイズ済みSVGを返す
    diagramSvg.value = svg
  } catch (e) {
    console.warn('Mermaid rendering failed:', e)
    diagramSvg.value = ''
    // 図のレンダリング失敗 = LLM の Mermaid 出力に Syntax Error。
    // 親 (GeneratePage) に通知して、問題ごと差し替え依頼させる。
    // 1問につき 1 回だけ依頼する (差し替え後の question_id 変化で
    // watch がフラグを再リセット)。
    if (!_regenerateRequested) {
      _regenerateRequested = true
      emit('diagram-error', {
        questionId: props.question.id,
        topic: props.question.topic,
        level: props.question.level,
        error: String(e?.message || e),
      })
    }
  }
}

onMounted(() => { if (props.question.diagram) renderDiagram() })
// FRONTEND-11: reset the regenerate-once guard when *either* the id
// changes (different question) OR the diagram source changes (the
// regenerate flow keeps the id but rewrites the source). Without the
// diagram-change reset, a regenerated question that's *also* broken
// would be silently skipped by the guard and never trigger another
// regen — the parent's per-question retry counter then never gets
// the second signal and the user is left with a broken card.
watch(() => props.question.id, () => { _regenerateRequested = false })
watch(() => props.question.diagram, () => {
  _regenerateRequested = false
  nextTick(renderDiagram)
})

const isCorrect = computed(
  () => props.userAnswer === props.question.answer
)

function choiceClass(key) {
  if (!props.revealed) {
    return props.userAnswer === key ? 'selected' : ''
  }
  if (key === props.question.answer) return 'correct'
  if (key === props.userAnswer)      return 'incorrect'
  return 'dimmed'
}
</script>

<style scoped>
.question-card {
  transition: border-color 0.3s, box-shadow 0.3s, transform 0.15s;
}
.question-card:hover {
  border-color: rgba(99,102,241,0.25);
  box-shadow: 0 6px 24px rgba(0,0,0,0.18);
}
.question-card.revealed { border-color: rgba(99,102,241,0.3); }
.question-card.is-regenerating {
  border-color: rgba(245,158,11,0.45);
  box-shadow: 0 0 0 1px rgba(245,158,11,0.18) inset;
}

.regen-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: -4px -4px 12px;
  padding: 8px 12px;
  background: rgba(245,158,11,0.10);
  border: 1px solid rgba(245,158,11,0.30);
  border-radius: 8px;
  font-size: 12px;
  color: var(--warning);
}

.q-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.q-number { font-size: 12px; font-weight: 700; color: var(--text-muted); }
.q-topic  { font-size: 12px; color: var(--text-muted); flex: 1; }

.result-badge {
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 700;
}
.result-badge.correct   { background: rgba(34,197,94,0.15);  color: var(--success); }
.result-badge.incorrect { background: rgba(239,68,68,0.15);  color: var(--danger);  }

.q-text {
  font-size: 14px;
  line-height: 1.7;
  margin-bottom: 16px;
  color: var(--text-primary);
}

/* ダイアグラム */
.q-diagram {
  margin-bottom: 16px;
  padding: 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow-x: auto;
  text-align: center;
}
.q-diagram :deep(svg) {
  max-width: 100%;
  height: auto;
}

/* ---- Mermaid テキスト可読性の安全網 ----
   themeVariables でカバーしきれない要素（特にpie/journey/sankeyの内部ラベル）
   に対して、暗背景でも読める明色テキストを強制する。 */
.q-diagram :deep(svg text),
.q-diagram :deep(svg .nodeLabel),
.q-diagram :deep(svg .edgeLabel),
.q-diagram :deep(svg .label) {
  fill: #f1f5f9 !important;
  color: #f1f5f9 !important;
}
.q-diagram :deep(svg .edgeLabel) {
  background-color: #1e293b !important;
}
.q-diagram :deep(svg .edgeLabel rect) {
  fill: #1e293b !important;
  opacity: 0.92;
}
/* pie 内ラベル（扇内）は背景が明色なので暗いテキスト */
.q-diagram :deep(svg .pieCircle ~ text),
.q-diagram :deep(svg text.slice) {
  fill: #0f172a !important;
}
/* legend テキストは図外なので明色 */
.q-diagram :deep(svg g.legend text),
.q-diagram :deep(svg .legend text) {
  fill: #f1f5f9 !important;
}
/* sequenceDiagram のメッセージテキスト */
.q-diagram :deep(svg .messageText),
.q-diagram :deep(svg .noteText),
.q-diagram :deep(svg .actor-line + text),
.q-diagram :deep(svg text.actor) {
  fill: #f1f5f9 !important;
  stroke: none !important;
}
/* gantt: タスクテキストの白背景化を防ぐ */
.q-diagram :deep(svg .taskText),
.q-diagram :deep(svg .taskTextOutsideRight),
.q-diagram :deep(svg .taskTextOutsideLeft) {
  fill: #f1f5f9 !important;
}
/* journey diagram のセクション/タスクラベル */
.q-diagram :deep(svg .section),
.q-diagram :deep(svg .face) {
  stroke: #6366f1 !important;
}

.choices { display: flex; flex-direction: column; gap: 8px; }

.choice-btn {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  transition: all 0.2s;
  width: 100%;
}
.choice-btn:hover:not(:disabled) {
  border-color: var(--accent);
  background: rgba(99,102,241,0.05);
}
.choice-btn.selected  { border-color: var(--accent);   background: rgba(99,102,241,0.1); }
.choice-btn.correct   { border-color: var(--success);  background: rgba(34,197,94,0.1);  }
.choice-btn.incorrect { border-color: var(--danger);   background: rgba(239,68,68,0.1);  }
.choice-btn.dimmed    { opacity: 0.4; }
.choice-btn:disabled  { cursor: default; }

.choice-key {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 4px;
  background: var(--border);
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}
.choice-text { flex: 1; font-size: 13px; line-height: 1.5; }
.choice-mark { font-size: 14px; font-weight: 700; color: var(--success); flex-shrink: 0; }
.choice-mark.wrong { color: var(--danger); }

.q-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
}

.explanation {
  margin-top: 16px;
  padding: 14px;
  background: rgba(99,102,241,0.05);
  border: 1px solid rgba(99,102,241,0.2);
  border-radius: 8px;
}
.explanation-header {
  font-size: 12px;
  font-weight: 700;
  color: var(--accent-hover);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.explanation-text {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-primary);
  white-space: pre-wrap;
}
.source-hint {
  margin-top: 10px;
  font-size: 11px;
  color: var(--text-muted);
  padding-top: 8px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 6px;
}
.source-link {
  color: var(--accent-hover);
  text-decoration: none;
  transition: all 0.15s;
}
.source-link:hover {
  color: var(--accent);
  text-decoration: underline;
}
</style>
