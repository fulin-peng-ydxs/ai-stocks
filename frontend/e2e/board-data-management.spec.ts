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
    // 三视口并发时后端会串行 DuckDB 查询，等待概览真实完成而非对初始占位断言。
    await expect(card.locator('.stat-val')).not.toHaveText('—', { timeout: 30_000 })
    await card.click()
    await expect(page.getByText('覆盖进度', { exact: true })).toBeVisible()
    await expect(page.getByText('成分覆盖', { exact: true })).toBeVisible()
    await expect(page.getByText('指数覆盖', { exact: true })).toBeVisible()
    await expect(page.getByTestId('overview-board-ingest')).toBeVisible()
    await page.getByTestId('overview-board-ingest').click()

    await expect(page).toHaveURL(/\/data\/ingest\?task_type=board&mode=update/)
    await expect(page.getByTestId('ingest-options-dialog')).toBeVisible()
    await expect(page.getByTestId('ingest-board-mode-update')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('ingest-board-type')).toBeVisible()
    await expect(page.getByTestId('ingest-board-stages')).toContainText('字典')
    await expect(page.getByTestId('ingest-board-stages')).toContainText('资金流')
    expect(consoleIssues).toEqual([])
  })

  test('定时板块采集保存明确的全量模式', async ({ page, request }) => {
    // 本用例显式注入两次 503 验证授权状态错误闭环；只豁免该预期 HTTP 状态。
    const consoleIssues = collectConsoleIssues(page, { allowedHttpStatuses: [503] })
    const auth = await loginAsDebugUser(page, request, 'debug_system')
    const headers = { authorization: `Bearer ${auth.accessToken}` }
    const jobName = `E2E 板块全量采集 ${Date.now()}`

    try {
      await openPageAndWaitForHeading(page, '/data/schedule', '任务调度')
      await expect(page.getByTestId('ths-login-cookie-btn')).toBeVisible()
      let settingsCalls = 0
      await page.route('**/api/data/settings', async (route) => {
        settingsCalls += 1
        if (settingsCalls === 1 || settingsCalls === 3) {
          await route.fulfill({
            status: 503,
            contentType: 'application/json',
            body: JSON.stringify({ detail: 'settings unavailable' }),
          })
          return
        }
        const secretStatus = settingsCalls === 2 ? 'usable' : 'unavailable'
        await route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify({
            code: 0,
            msg: 'ok',
            data: {
              groups: [{
                key: 'ths_board',
                label: '同花顺板块',
                fields: [{
                  path: 'ths_board.login_cookie',
                  label: '登录 Cookie',
                  type: 'password',
                  value: secretStatus === 'usable' ? '••••••已设置' : '',
                  default: '',
                  overridden: true,
                  secret_status: secretStatus,
                }],
              }],
            },
          }),
        })
      })
      await page.getByTestId('ths-login-cookie-btn').click()
      const cookieDialog = page.getByTestId('ths-login-cookie-dialog')
      await expect(cookieDialog).toBeVisible()
      await expect(cookieDialog.getByTestId('ths-login-cookie-status')).toContainText('授权配置状态加载失败')
      await expect(cookieDialog.getByTestId('ths-login-cookie-input')).toHaveCount(0)
      await expect(cookieDialog.getByRole('button', { name: '清除页面配置' })).toHaveCount(0)
      await cookieDialog.getByRole('button', { name: '重新加载' }).click()
      await expect(cookieDialog.getByTestId('ths-login-cookie-input')).toHaveValue('••••••已设置')
      await cookieDialog.getByRole('button', { name: '取消' }).click()

      // 失败状态关闭后重开必须重新请求，不能沿用上一次成功或把失败压成“未设置”。
      await page.getByTestId('ths-login-cookie-btn').click()
      await expect(cookieDialog.getByTestId('ths-login-cookie-status')).toContainText('授权配置状态加载失败')
      await cookieDialog.getByRole('button', { name: '取消' }).click()
      await page.getByTestId('ths-login-cookie-btn').click()
      await expect(cookieDialog).toContainText('已存密文无法解密，当前采集不会使用它')
      await page.getByTestId('ths-login-cookie-input').fill('e2e-ui-only-cookie')
      await expect(page.getByTestId('ths-login-cookie-save')).toBeEnabled()
      await cookieDialog.getByRole('button', { name: '取消' }).click()

      await page.getByTestId('schedule-create').click()
      await page.getByTestId('schedule-name').fill(jobName)
      await page.getByTestId('schedule-task-type').click()
      await page.getByRole('option', { name: '板块采集' }).click()

      await expect(page.getByTestId('schedule-board-mode')).toBeVisible()
      await page.getByTestId('schedule-board-mode-backfill').click()
      await page.getByTestId('schedule-board-type-concept').click()
      await page.getByTestId('schedule-board-stages').getByText('字典', { exact: true }).click()
      await page.getByTestId('schedule-board-stages').getByText('成分', { exact: true }).click()
      await page.getByTestId('schedule-enabled').click()
      await page.getByTestId('schedule-save').click()

      const jobRow = page.getByRole('row').filter({ hasText: jobName })
      await expect(jobRow).toContainText('板块采集·全量回填')
      const response = await request.get(`${API_URL}/data/schedules`, { headers })
      expect(response.ok()).toBe(true)
      const body = await response.json()
      const job = body.data.jobs.find((item: { name: string }) => item.name === jobName)
      expect(job?.params).toEqual({
        mode: 'backfill', board_type: 'concept', only: ['bar', 'fund'],
      })
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
