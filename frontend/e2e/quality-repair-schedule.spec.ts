import { expect, test } from '@playwright/test'

import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { DEFAULT_E2E_API_URL } from './helpers/e2e-backend-health.mjs'

const API_URL = process.env.E2E_API_URL || DEFAULT_E2E_API_URL

test.describe('质检问题定时恢复', () => {
  test('可按问题类型创建定时任务并保存动态恢复参数', async ({ page, request }) => {
    const consoleIssues = collectConsoleIssues(page)

    const auth = await loginAsDebugUser(page, request, 'debug_system')
    const headers = { authorization: `Bearer ${auth.accessToken}` }
    const jobName = `E2E 行情缺口恢复 ${Date.now()}`

    try {
      await page.goto('/data/schedule')
      await page.getByTestId('schedule-create').click()
      await expect(page.getByTestId('schedule-dialog')).toBeVisible()

      await page.getByTestId('schedule-name').fill(jobName)
      await page.getByTestId('schedule-task-type').click()
      await page.getByRole('option', { name: '质检问题恢复' }).click()

      await expect(page.getByTestId('schedule-issue-type')).toBeVisible()
      await page.getByTestId('schedule-issue-type').click()
      await page.getByRole('option', { name: '行情缺口(疑似漏采)' }).click()
      await page.getByTestId('schedule-enabled').click()
      await page.getByTestId('schedule-save').click()

      const jobRow = page.getByRole('row').filter({ hasText: jobName })
      await expect(jobRow).toContainText('质检问题恢复·行情缺口(疑似漏采)')
      await expect(jobRow.getByRole('switch')).not.toBeChecked()

      const response = await request.get(`${API_URL}/data/schedules`, { headers })
      expect(response.ok()).toBe(true)
      const body = await response.json()
      const job = body.data.jobs.find((item: { name: string }) => item.name === jobName)
      expect(job?.params).toEqual({ issue_type: 'data_gap' })
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
