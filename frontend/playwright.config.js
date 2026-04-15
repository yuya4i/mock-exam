/**
 * Playwright configuration for the QuizGen e2e suite.
 *
 * Tests do NOT depend on the Python backend or Ollama — every /api/*
 * call is mocked at the page-route level (see e2e/_helpers.js). This
 * keeps the suite runnable in CI without any service infra and pins
 * test outcomes to the frontend behavior we actually want to assert.
 */
import { defineConfig, devices } from '@playwright/test'

const PORT = 1234

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  timeout: 30_000,
  expect: { timeout: 5_000 },

  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: process.env.CI ? 'retain-on-failure' : 'off',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Vite dev server: started once per `playwright test` invocation.
  // `reuseExistingServer` is true outside CI so re-running tests against
  // a local `npm run dev` is instant.
  webServer: {
    command: 'npm run dev',
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
})
