/**
 * useSSE.js
 * --------------------------------------------------------------------
 * Server-Sent Events client built on `fetch` + ReadableStream.
 *
 * Why not the browser's `EventSource`?
 *   - EventSource cannot set custom headers, which means it cannot send
 *     `Authorization: Bearer <token>`. Until P1-G the scrape-stream
 *     endpoint had a query-parameter carve-out (`?api_token=...`) just
 *     to work around that limitation. Tokens in URLs leak in access
 *     logs, browser histories, and Referer headers, so the carve-out
 *     was a known liability.
 *   - `fetch` returns a ReadableStream we can manually parse for the
 *     SSE wire format ("event: name\ndata: json\n\n"). It supports any
 *     header, any verb, and respects AbortSignal cleanly.
 *
 * Single shared helper, used by both useQuizStore (POST /api/quiz/generate)
 * and useScrapeProgressStore (GET /api/content/scrape-stream).
 */
import { API_TOKEN_STORAGE_KEY, API_TOKEN_CLEARED_EVENT } from '@/composables/useApi'

/**
 * Open an SSE stream and dispatch each named event to ``onEvent``.
 *
 * The promise resolves when the server closes the stream (i.e. the
 * normal terminal `done` event has already been delivered to ``onEvent``)
 * or rejects on transport / parse failure.
 *
 * @param {string} url
 * @param {{ method?: 'GET'|'POST', body?: any, headers?: object }} init
 * @param {(eventType: string, data: any) => void} onEvent
 * @param {AbortSignal} [signal]
 * @returns {Promise<void>}
 */
export async function streamSSE(url, init = {}, onEvent, signal) {
  const { method = 'POST', body, headers = {} } = init

  // Auto-attach Authorization if the user has stored a token. Same key
  // as useApi.js so the axios interceptor and SSE share state.
  const finalHeaders = { Accept: 'text/event-stream', ...headers }
  if (body !== undefined && finalHeaders['Content-Type'] === undefined) {
    finalHeaders['Content-Type'] = 'application/json'
  }
  try {
    const token = localStorage.getItem(API_TOKEN_STORAGE_KEY)
    if (token && token.trim()) {
      finalHeaders.Authorization = `Bearer ${token.trim()}`
    }
  } catch (_) {
    // Private browsing / restricted localStorage — proceed without auth.
  }

  const response = await fetch(url, {
    method,
    headers: finalHeaders,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  })

  if (!response.ok) {
    let errBody = {}
    try { errBody = await response.json() } catch (_) {}
    const status = response.status
    if (status === 401) {
      // FRONTEND-5: drop the bad token so we don't loop on it, and
      // notify the Pinia settings store so the UI input clears.
      try { localStorage.removeItem(API_TOKEN_STORAGE_KEY) } catch (_) {}
      try {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent(API_TOKEN_CLEARED_EVENT))
        }
      } catch (_) {}
      throw new Error(
        '認証に失敗しました。保存していたトークンを破棄しました。' +
        '設定画面から API_TOKEN を再設定してください。',
      )
    }
    throw new Error(errBody.error || `HTTP ${status}`)
  }

  if (!response.body) {
    throw new Error('SSE 応答にボディがありません。')
  }

  // FRONTEND-4: pin the reader+stream cleanup in a finally so an
  // AbortSignal cancellation, a parse-throw, or any other early exit
  // doesn't leave the underlying ReadableStream locked forever (which
  // pins the response, the connection, and the parsed-event closures
  // alive). Both releaseLock and body.cancel are best-effort — they
  // throw if the reader was never acquired or the stream is already
  // released; we swallow those because the only correct response is
  // "we tried".
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // Events are separated by a blank line. Hold the trailing partial
      // chunk in `buffer` until the next read completes it.
      const parts = buffer.split('\n\n')
      buffer = parts.pop()

      for (const part of parts) {
        if (!part.trim()) continue
        let eventType = 'message'
        let eventData = ''
        for (const line of part.split('\n')) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7)
          } else if (line.startsWith('data: ')) {
            // Multiple data: lines per event are part of the spec; we
            // only see single-line JSON in practice.
            eventData = line.slice(6)
          }
        }
        if (!eventData) continue
        let parsed
        try {
          parsed = JSON.parse(eventData)
        } catch (_) {
          // Malformed data line — skip, do not propagate (server-side
          // parsing is supposed to guarantee JSON).
          continue
        }
        onEvent(eventType, parsed)
      }
    }
  } finally {
    try { reader.releaseLock() } catch (_) {}
    try { await response.body.cancel() } catch (_) {}
  }
}
