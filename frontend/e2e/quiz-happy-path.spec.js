/**
 * Happy path: the user opens GeneratePage, picks a model, types a URL,
 * clicks "問題を生成する", and sees questions stream in via SSE before
 * the `done` event.
 *
 * The whole stack is mocked via Playwright `page.route()` — no Flask,
 * no Ollama. The point of this test is to lock in the *frontend* SSE
 * contract: that streamSSE() (P1-G) correctly parses event frames from
 * a real fetch+ReadableStream response and that questions are appended
 * to the store as they arrive.
 */
import { test, expect } from '@playwright/test'
import { mockBackend, quizSseBody } from './_helpers.js'

test('user can generate quiz and see two questions stream in', async ({ page }) => {
  await mockBackend(page)

  // Quiz endpoint returns a deterministic SSE body with 2 questions.
  await page.route('**/api/quiz/generate', route => route.fulfill({
    status: 200,
    headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
    body: quizSseBody({ count: 2 }),
  }))

  await page.goto('/')

  // Wait for the model dropdown to be populated by /api/models.
  const modelSelect = page.locator('select.form-select').first()
  await expect(modelSelect).toBeVisible()
  await modelSelect.selectOption('qwen2.5:7b')

  // Source URL.
  const sourceInput = page.locator('input[role="combobox"]')
  await sourceInput.fill('https://example.com/docs')

  // Click the primary CTA. The label switches between
  // "問題を生成する" (idle) and "生成中..." (running).
  await page.getByRole('button', { name: /問題を生成する/ }).click()

  // The two streamed questions should appear in DOM order.
  await expect(page.locator('text=Question 1: what?')).toBeVisible({ timeout: 10_000 })
  await expect(page.locator('text=Question 2: what?')).toBeVisible({ timeout: 10_000 })

  // After `done`, the Reset button should appear.
  await expect(page.getByRole('button', { name: /リセット/ })).toBeVisible()
})
