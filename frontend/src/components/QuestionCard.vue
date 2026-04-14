<template>
  <div class="question-card card" :class="{ 'revealed': revealed }">
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

    <!-- Mermaid図表（存在する場合） -->
    <div v-if="question.diagram" class="q-diagram" ref="diagramEl">
      <!-- mermaid.render() が返すサニタイズ済みSVGを描画 -->
      <div v-if="diagramSvg" v-html="diagramSvg"></div>
      <!-- フォールバック: レンダリング失敗時はソースをコードブロックで表示 -->
      <pre v-else-if="question.diagram" class="diagram-fallback">{{ question.diagram }}</pre>
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
  question:   { type: Object,  required: true },
  index:      { type: Number,  required: true },
  userAnswer: { type: String,  default: null  },
  revealed:   { type: Boolean, default: false },
  sourceInfo: { type: Object,  default: null  },
})

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
    if (matched?.url) return matched.url
  }

  const src = info.source
  if (src && (src.startsWith('http://') || src.startsWith('https://'))) {
    return src
  }
  return ''
})

defineEmits(['answer', 'reveal'])

const diagramEl = ref(null)
const diagramSvg = ref('')

async function renderDiagram() {
  if (!props.question.diagram || !diagramEl.value) return
  try {
    const { default: mermaid } = await import('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs')
    mermaid.initialize({ startOnLoad: false, theme: 'dark' })
    const id = `mermaid-${props.question.id}`
    const { svg } = await mermaid.render(id, props.question.diagram)
    // mermaid.render はサニタイズ済みSVGを返す
    diagramSvg.value = svg
  } catch (e) {
    console.warn('Mermaid rendering failed:', e)
    diagramSvg.value = ''
  }
}

onMounted(() => { if (props.question.diagram) renderDiagram() })
watch(() => props.question.diagram, () => nextTick(renderDiagram))

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
.question-card { transition: border-color 0.3s; }
.question-card.revealed { border-color: rgba(99,102,241,0.3); }

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
.diagram-fallback {
  font-size: 11px;
  color: var(--text-muted);
  white-space: pre-wrap;
  text-align: left;
  margin: 0;
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
