import { expect, test } from '@playwright/test'

import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { DEFAULT_E2E_API_URL } from './helpers/e2e-backend-health.mjs'
import { openPageAndWaitForHeading } from './helpers/navigation'

const API_URL = process.env.E2E_API_URL || DEFAULT_E2E_API_URL

test.describe('板块数据管理闭环', () => {
  test('数据概览展示板块覆盖并下钻到增量采集', async ({ page, request }) => {
    const consoleIssues = collectConsoleIssues(page)
    await loginAsDebugUser(page, request, 'debug_system')
    await openPageAndWaitForHeading(page, '/data/overview', '数据概览')

    const card = page.getByTestId('overview-board-card')
    await expect(card).toBeVisible({ timeout: 30_000 })
    await expect(card).toContainText('概念')
    await expect(card).toContainText('覆盖 成分')
    await expect(card).toContainText('最新 指数')
    await card.click()

    await expect(page).toHaveURL(/\/data\/ingest\?task_type=board&mode=update/)
    await expect(page.getByTestId('ingest-options-dialog')).toBeVisible()
    await expect(page.getByRole('radio', { name: '增量' })).toBeChecked()
    expect(consoleIssues).toEqual([])
  })

  test('定时板块采集保存明确的全量模式', async ({ page, request }) => {
    const consoleIssues = collectConsoleIssues(page)
    const auth = await loginAsDebugUser(page, request, 'debug_system')
    const headers = { authorization: `Bearer ${auth.accessToken}` }
    const jobName = `E2E 板块全量采集 ${Date.now()}`

    try {
      await openPageAndWaitForHeading(page, '/data/schedule', '任务调度')
      await page.getByTestId('schedule-create').click()
      await page.getByTestId('schedule-name').fill(jobName)
      await page.getByTestId('schedule-task-type').click()
      await page.getByRole('option', { name: '板块采集' }).click()

      await expect(page.getByTestId('schedule-board-mode')).toBeVisible()
      await page.getByTestId('schedule-board-mode-backfill').click()
      await page.getByTestId('schedule-enabled').click()
      await page.getByTestId('schedule-save').click()

      const jobRow = page.getByRole('row').filter({ hasText: jobName })
      await expect(jobRow).toContainText('板块采集·全量回填')
      const response = await request.get(`${API_URL}/data/schedules`, { headers })
      expect(response.ok()).toBe(true)
      const body = await response.json()
      const job = body.data.jobs.find((item: { name: string }) => item.name === jobName)
      expect(job?.params).toEqual({ mode: 'backfill' })
      expect(job?.enabled).toBe(false)
      expect(consoleIssues).toEqual([])
    } finally {
      const response = await request.get(`${API_URL}/data/schedules`, { headers })
      if (response.ok()) {
        const body = await response.json()
        const job = body.data.jobs.find((item: { name: string }) => item.name === jobName)
        if (job?.id) await request.delete(`${API_URL}/data/schedules/${job.id}`, { headers })
      }
    }
  })
})
