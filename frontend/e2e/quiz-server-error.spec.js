/**
 * Failure path: the backend returns a 422 with the SSRF deny message
 * (the realistic shape after P0-4 hardening). The UI should surface
 * the Japanese error string in an .alert-error block instead of
 * showing question cards.
 *
 * This locks the frontend behavior we shipped in P1-G: streamSSE()
 * rejects with the server's `error` field on non-2xx, and the store's
 * try/catch puts that string into `quizStore.error` for the template
 * to render.
 */
import { test, expect } from '@playwright/test'
import { mockBackend } from './_helpers.js'

test('SSRF-denied URL surfaces the backend error in the UI', async ({ page }) => {
  await mockBackend(page)

  // Preview is hit first when the user clicks プレビュー — return the
  // 422 SSRF rejection message that safe_fetch produces in real life.
  await page.route('**/api/content/preview', route => route.fulfill({
    status: 422,
    contentType: 'application/json',
    body: JSON.stringify({
      error: 'プライベート/ループバック/リンクローカル宛のアクセスは拒否されました: 127.0.0.1',
    }),
  }))

  await page.goto('/')

  await page.locator('input[role="combobox"]').fill('https://127.0.0.1/')
  await page.getByRole('button', { name: /プレビュー/ }).click()

  await expect(page.locator('.alert-error')).toContainText(
    'プライベート/ループバック/リンクローカル宛のアクセスは拒否されました',
    { timeout: 5_000 },
  )
})


test('quiz/generate 401 unauthorized shows the auth error message', async ({ page }) => {
  await mockBackend(page)

  // Set a stale token in localStorage before the SPA loads — useApi.js
  // and useSSE.js both pick this up and attach an Authorization header.
  await page.addInitScript(() => localStorage.setItem('apiToken', 'stale-token'))

  // Backend rejects with 401 (matches security.py middleware response).
  await page.route('**/api/quiz/generate', route => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ error: '認証に失敗しました。' }),
  }))

  await page.goto('/')

  const modelSelect = page.locator('select.form-select').first()
  await expect(modelSelect).toBeVisible()
  await modelSelect.selectOption('qwen2.5:7b')

  await page.locator('input[role="combobox"]').fill('https://example.com/docs')
  await page.getByRole('button', { name: /問題を生成する/ }).click()

  // useSSE.js translates a 401 response to a Settings-pointing message
  // before it ever reaches the store error field.
  await expect(page.locator('.alert-error')).toContainText(
    '認証に失敗しました',
    { timeout: 5_000 },
  )
})
