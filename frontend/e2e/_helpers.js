/**
 * Shared mocking utilities for the e2e suite.
 *
 * Every test in this directory registers `mockBackend(page)` at the top of
 * its setup so the SPA never reaches a real network. Specific tests can
 * override individual routes after this baseline by registering more
 * `page.route()` handlers — Playwright resolves the most recently
 * registered route handler first.
 */

const SAMPLE_DOCUMENTS = [
  {
    id: 1,
    title: 'Sample Doc',
    url: 'https://example.com/docs',
    source_type: 'url_deep',
    page_count: 3,
    doc_types: ['table', 'pdf'],
    scraped_at: '2026-04-10T12:00:00Z',
  },
]

const SAMPLE_RESULTS = { sessions: [] }
const SAMPLE_CATEGORIES = { categories: [] }
const SAMPLE_BREAKDOWN = { categories: [] }

/** SSE wire format helper. Returns "event: name\ndata: json\n\n". */
function sse(event, data) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

/** Build a deterministic SSE body for a /api/quiz/generate response.
 *
 * The `done` event carries the same `questions` array that was streamed
 * in via `question` events — this matches the real backend (see
 * quiz_service.generate_incremental), and is required by the frontend
 * store, which overwrites `result.value` on `done`.
 */
export function quizSseBody({ sessionId = 'sess-test', count = 2 } = {}) {
  const questions = []
  for (let i = 1; i <= count; i++) {
    questions.push({
      id: `Q${String(i).padStart(3, '0')}`,
      level: 'K2',
      topic: `Topic ${i}`,
      question: `Question ${i}: what?`,
      diagram: '',
      choices: { a: 'opt-a', b: 'opt-b', c: 'opt-c', d: 'opt-d' },
      answer: 'b',
      explanation: 'Because.',
      source_hint: '',
    })
  }

  const sourceInfo = {
    session_id: sessionId,
    title: 'Test Document',
    source: 'https://example.com',
    type: 'url_deep',
    depth: 1,
    doc_types: ['table'],
    page_count: 1,
    document_id: 1,
  }

  const events = [sse('source_info', sourceInfo)]
  for (let i = 0; i < count; i++) {
    events.push(sse('progress', { current: i + 1, total: count, status: 'generating' }))
    events.push(sse('question', questions[i]))
  }
  events.push(sse('done', {
    session_id: sessionId,
    generated_at: '2026-04-15T00:00:00Z',
    model: 'qwen2.5:7b',
    question_count: count,
    questions,
    source_info: sourceInfo,
  }))
  return events.join('')
}

/** Build a deterministic SSE body for a /api/content/scrape-stream response. */
export function scrapeSseBody({ pages = 1 } = {}) {
  const events = []
  for (let i = 1; i <= pages; i++) {
    events.push(sse('progress', {
      url: `https://example.com/page-${i}`,
      depth: 0,
      status: 'scraped',
      pages_found: pages,
      total_visited: i,
    }))
  }
  events.push(sse('done', {
    document_id: 1,
    title: 'Test Document',
    page_count: pages,
  }))
  return events.join('')
}

/** Install the baseline mocks every test starts from. */
export async function mockBackend(page) {
  // Health: pretend Ollama is connected so the navbar dot turns green
  // and capability checks don't fail.
  await page.route('**/api/health', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      status: 'ok',
      ollama: 'connected',
      ollama_url: 'http://localhost:11434',
    }),
  }))

  await page.route('**/api/system/specs', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      ram_total_gb: 16,
      ram_available_gb: 8,
      cpu_count: 8,
      platform: 'linux',
    }),
  }))

  await page.route('**/api/models', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      models: [
        { name: 'qwen2.5:7b', size: 4_300_000_000, modified_at: '2026-04-01T00:00:00Z' },
        { name: 'llama3.1:8b', size: 4_700_000_000, modified_at: '2026-04-02T00:00:00Z' },
      ],
    }),
  }))

  await page.route('**/api/documents*', route => {
    const url = route.request().url()
    if (/\/api\/documents\/by-url/.test(url)) {
      // Default to "no existing document" so the existing-URL banner
      // does not appear in tests that don't opt in.
      return route.fulfill({ status: 404, contentType: 'application/json',
        body: JSON.stringify({ error: '見つかりません' }) })
    }
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ documents: SAMPLE_DOCUMENTS }),
    })
  })

  await page.route('**/api/results', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify(SAMPLE_RESULTS),
  }))
  await page.route('**/api/results/categories', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify(SAMPLE_CATEGORIES),
  }))
  await page.route('**/api/results/categories/breakdown', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify(SAMPLE_BREAKDOWN),
  }))

  // Default scrape-stream mock: a single-page success. Tests that need
  // a different scenario can override this with their own page.route().
  await page.route('**/api/content/scrape-stream**', route => route.fulfill({
    status: 200,
    headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
    body: scrapeSseBody({ pages: 1 }),
  }))
}
