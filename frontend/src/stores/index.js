import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api, { API_TOKEN_STORAGE_KEY } from '@/composables/useApi'
import { streamSSE } from '@/composables/useSSE'

// ======================================================================
// 設定ストア
// ======================================================================
export const useSettingsStore = defineStore('settings', () => {
  const ollamaUrl = ref(
    localStorage.getItem('ollamaUrl') || 'http://localhost:11434'
  )

  // API token: 未設定 (空) ならバックエンドの API_TOKEN も未設定前提。
  // 設定時は useApi.js のリクエストインターセプターが自動で Authorization
  // ヘッダに乗せる。機密値なので localStorage キーは共通定数で管理する。
  const apiToken = ref(localStorage.getItem(API_TOKEN_STORAGE_KEY) || '')

  function setOllamaUrl(url) {
    ollamaUrl.value = url
    localStorage.setItem('ollamaUrl', url)
  }

  function setApiToken(token) {
    const trimmed = (token || '').trim()
    apiToken.value = trimmed
    if (trimmed) {
      localStorage.setItem(API_TOKEN_STORAGE_KEY, trimmed)
    } else {
      localStorage.removeItem(API_TOKEN_STORAGE_KEY)
    }
  }

  return { ollamaUrl, apiToken, setOllamaUrl, setApiToken }
})

// ======================================================================
// モデルストア
// ======================================================================
export const useModelsStore = defineStore('models', () => {
  const models   = ref([])
  const loading  = ref(false)
  const error    = ref(null)
  const settings = useSettingsStore()

  // ホストPCのスペック（/api/system/specs）
  // { ram_total_gb, ram_available_gb, cpu_count, platform } | null
  const systemSpecs = ref(null)
  const specsError  = ref(null)

  async function fetchModels() {
    loading.value = true
    error.value   = null
    try {
      const res = await api.get('/models')
      models.value = res.data.models || []
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
    // モデル取得時にシステムスペックも併せて取得（未取得時のみ）
    if (systemSpecs.value === null) {
      fetchSystemSpecs().catch(() => {})
    }
  }

  async function fetchSystemSpecs() {
    specsError.value = null
    try {
      const res = await api.get('/system/specs')
      systemSpecs.value = res.data || null
    } catch (e) {
      specsError.value  = e.message
      systemSpecs.value = null
    }
  }

  return {
    models, loading, error,
    systemSpecs, specsError,
    fetchModels, fetchSystemSpecs,
  }
})

// ======================================================================
// クイズストア（1問ずつSSEストリーミング生成）
// ======================================================================
export const useQuizStore = defineStore('quiz', () => {
  const result      = ref(null)
  const generating  = ref(false)
  const error       = ref(null)
  const progress    = ref({ current: 0, total: 0, status: '' })

  // ユーザーの解答状態
  const userAnswers = ref({})
  const revealed    = ref({})

  // 生成中止用
  let abortController = null

  const score = computed(() => {
    if (!result.value?.questions) return null
    const qs = result.value.questions
    const correct = qs.filter(
      (q) => userAnswers.value[q.id] === q.answer
    ).length
    return { correct, total: qs.length }
  })

  async function generate(params) {
    generating.value  = true
    error.value       = null
    result.value      = null
    userAnswers.value = {}
    revealed.value    = {}
    progress.value    = { current: 0, total: params.count, status: 'scraping' }

    abortController = new AbortController()

    const payload = {
      source:     params.source,
      model:      params.model,
      count:      params.count,
      levels:     params.levels,
      difficulty: params.difficulty,
      depth:      params.depth     ?? 1,
      doc_types:  params.doc_types ?? ['table', 'csv', 'pdf', 'png'],
    }

    const baseUrl = api.defaults.baseURL || '/api'

    try {
      // streamSSE が Authorization 自動付与・SSE 行パースを集約しているので、
      // ストアはイベントハンドラに専念する。
      await streamSSE(
        `${baseUrl}/quiz/generate`,
        { method: 'POST', body: payload },
        _handleEvent,
        abortController.signal,
      )
    } catch (e) {
      if (e.name !== 'AbortError') {
        error.value = e.message
      }
    } finally {
      generating.value = false
      abortController = null
    }
  }

  function _handleEvent(type, data) {
    switch (type) {
      case 'source_info':
        // 結果オブジェクトを初期化（questionsは空配列で開始）
        result.value = {
          session_id:  data.session_id,
          source_info: data,
          model:       '',
          questions:   [],
        }
        progress.value.status = 'generating'
        break

      case 'progress':
        progress.value = {
          current: data.current,
          total:   data.total,
          status:  'generating',
        }
        break

      case 'question':
        // 問題が1つ到着 → リアクティブに追加
        if (result.value) {
          result.value.questions.push(data)
        }
        break

      case 'question_error':
        // 個別の問題生成失敗（全体は止めない）
        console.warn(`Q${data.qnum} 生成失敗: ${data.error}`)
        break

      case 'done':
        // 最終結果で上書き（DB保存済みデータと同期）
        result.value = data
        progress.value = {
          current: data.question_count || data.questions?.length || 0,
          total:   data.question_count || data.questions?.length || 0,
          status:  'done',
        }
        // 結果ストアを更新
        try {
          const resultsStore = useResultsStore()
          resultsStore.fetchResults()
        } catch (_) {}
        break

      case 'error':
        error.value = data.message || '問題生成中にエラーが発生しました'
        break
    }
  }

  function abort() {
    abortController?.abort()
  }

  function setAnswer(questionId, choice) {
    userAnswers.value[questionId] = choice
  }

  function revealAnswer(questionId) {
    revealed.value[questionId] = true
  }

  function revealAll() {
    result.value?.questions.forEach((q) => {
      revealed.value[q.id] = true
    })
  }

  function reset() {
    abort()
    result.value      = null
    userAnswers.value = {}
    revealed.value    = {}
    error.value       = null
    progress.value    = { current: 0, total: 0, status: '' }
  }

  return {
    result, generating, error, progress,
    userAnswers, revealed, score,
    generate, abort, setAnswer, revealAnswer, revealAll, reset,
  }
})

// ======================================================================
// ドキュメントストア
// ======================================================================
export const useDocumentsStore = defineStore('documents', () => {
  const documents = ref([])
  const loading   = ref(false)
  const error     = ref(null)
  const search    = ref('')

  const filtered = computed(() => {
    if (!search.value) return documents.value
    const q = search.value.toLowerCase()
    return documents.value.filter(
      (d) =>
        (d.title || '').toLowerCase().includes(q) ||
        (d.url || '').toLowerCase().includes(q)
    )
  })

  async function fetchDocuments() {
    loading.value = true
    error.value   = null
    try {
      const res = await api.get('/documents')
      documents.value = res.data.documents || []
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function deleteDocument(id) {
    await api.delete(`/documents/${id}`)
    documents.value = documents.value.filter((d) => d.id !== id)
  }

  async function getDocument(id) {
    const res = await api.get(`/documents/${id}`)
    return res.data
  }

  return { documents, loading, error, search, filtered, fetchDocuments, deleteDocument, getDocument }
})

// ======================================================================
// 結果ストア
// ======================================================================
export const useResultsStore = defineStore('results', () => {
  const sessions   = ref([])
  const categories = ref([])
  const breakdown  = ref([])
  const loading    = ref(false)
  const error      = ref(null)

  const totalSessions = computed(() => sessions.value.length)

  const averageScore = computed(() => {
    const scored = sessions.value.filter((s) => s.score_total > 0)
    if (scored.length === 0) return 0
    const sum = scored.reduce((acc, s) => acc + (s.score_correct / s.score_total) * 100, 0)
    return Math.round(sum / scored.length)
  })

  const totalQuestions = computed(() =>
    sessions.value.reduce((acc, s) => acc + (s.question_count || 0), 0)
  )

  async function fetchResults() {
    loading.value = true
    error.value   = null
    try {
      const [sessRes, catRes, bdRes] = await Promise.all([
        api.get('/results'),
        api.get('/results/categories'),
        api.get('/results/categories/breakdown'),
      ])
      sessions.value   = sessRes.data.sessions   || []
      categories.value = catRes.data.categories   || []
      breakdown.value  = bdRes.data.categories   || []
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function getSession(sessionId) {
    const res = await api.get(`/results/${sessionId}`)
    return res.data
  }

  async function saveAnswers(sessionId, answers, scoreCorrect, scoreTotal) {
    await api.post(`/results/${sessionId}/answers`, {
      answers,
      score_correct: scoreCorrect,
      score_total:   scoreTotal,
    })
    await fetchResults()
  }

  async function deleteSession(sessionId) {
    await api.delete(`/results/${sessionId}`)
    sessions.value = sessions.value.filter((s) => s.session_id !== sessionId)
  }

  return {
    sessions, categories, breakdown, loading, error,
    totalSessions, averageScore, totalQuestions,
    fetchResults, getSession, saveAnswers, deleteSession,
  }
})

// ======================================================================
// スクレイピング経過ストア (P1-G で fetch+stream に統一)
// ======================================================================
export const useScrapeProgressStore = defineStore('scrapeProgress', () => {
  const events    = ref([])
  const isScraping = ref(false)
  const summary   = ref({ pagesFound: 0 })
  const error     = ref(null)

  let abortController = null

  async function startScrape(source, depth, docTypes) {
    // 前回の接続をクリーンアップ
    stopScrape()

    events.value    = []
    isScraping.value = true
    error.value     = null
    summary.value   = { pagesFound: 0 }

    abortController = new AbortController()

    const baseUrl = api.defaults.baseURL || '/api'
    const params = new URLSearchParams({
      source,
      depth:     String(depth),
      doc_types: docTypes.join(','),
    })

    function handleEvent(type, data) {
      switch (type) {
        case 'progress': {
          events.value.push({
            type:   'progress',
            url:    data.url,
            depth:  data.depth,
            status: 'loading',
            pages_found: data.pages_found,
          })
          summary.value.pagesFound = data.pages_found || events.value.length
          break
        }
        case 'done': {
          events.value.forEach((ev) => { ev.status = 'done' })
          events.value.push({
            type:        'done',
            document_id: data.document_id,
            title:       data.title,
            status:      'done',
          })
          summary.value.pagesFound = data.page_count || summary.value.pagesFound
          break
        }
        case 'error': {
          error.value = data?.message || 'スクレイピングエラー'
          break
        }
      }
    }

    try {
      // P1-G: GET + fetch+stream に切り替え。EventSource をやめたので
      // Authorization ヘッダが付き、`?api_token=` 経由のフォールバック
      // (アクセスログ汚染) は撤去された。
      await streamSSE(
        `${baseUrl}/content/scrape-stream?${params}`,
        { method: 'GET' },
        handleEvent,
        abortController.signal,
      )
      // ストリーム正常終了: まだ loading のイベントを done に確定。
      events.value.forEach((ev) => {
        if (ev.status === 'loading') ev.status = 'done'
      })
    } catch (e) {
      if (e.name !== 'AbortError') {
        error.value = e.message || 'スクレイピング中にエラーが発生しました'
      }
    } finally {
      isScraping.value = false
      abortController = null
    }
  }

  function stopScrape() {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    isScraping.value = false
  }

  function reset() {
    stopScrape()
    events.value  = []
    error.value   = null
    summary.value = { pagesFound: 0 }
  }

  return {
    events, isScraping, summary, error,
    startScrape, stopScrape, reset,
  }
})
