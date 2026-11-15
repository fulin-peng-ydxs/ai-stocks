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
    await expect(card.locator('.data-metric-value')).not.toHaveText('—', { timeout: 30_000 })
    await card.getByRole('button', { name: '查看板块', exact: true }).click()
    await expect(page.getByText('覆盖进度', { exact: true })).toBeVisible()
    await expect(page.getByText(/^成分覆盖\s*\?$/)).toBeVisible()
    await expect(page.getByText(/^指数覆盖\s*\?$/)).toBeVisible()
    await expect(page.getByTestId('overview-board-ingest')).toBeVisible()
    await page.getByTestId('overview-board-ingest').click()

    // 采集页消费一次性参数后清理 URL；以下继续检查实际弹窗及增量参数。
    await expect(page).toHaveURL(/\/data\/ingest$/)
    await expect(page.getByTestId('ingest-options-dialog')).toBeVisible()
    await expect(page.getByTestId('ingest-board-mode-update')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('ingest-board-type')).toBeVisible()
    await expect(page.getByTestId('ingest-board-stages')).toContainText('字典')
    await expect(page.getByTestId('ingest-board-stages')).toContainText('资金流')
    expect(consoleIssues).toEqual([])
  })

  test('系统设置凭据读取失败可重试且敏感输入防自动填充', async ({ page, request }) => {
    // 本用例显式注入两次 503 验证授权状态错误闭环；只豁免该预期 HTTP 状态。
    const consoleIssues = collectConsoleIssues(page, { allowedHttpStatuses: [503] })
    await loginAsDebugUser(page, request, 'debug_system')
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
    // 凭据已统一到系统设置；保留原失败/重试、重新进入及防自动填充契约。
    await openPageAndWaitForHeading(page, '/system/config/system', '系统设置')
    const settingsRegion = page.getByTestId('layout-grow-region')
    await expect(settingsRegion.getByText('服务暂时不可用，请稍后重试', { exact: true })).toBeVisible()
    const cookieInput = page.getByRole('region', { name: '同花顺板块', exact: true })
      .locator('input[type="password"]')
    await expect(cookieInput).toHaveCount(0)
    await expect(page.getByRole('button', { name: '清除已存配置', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: '重试', exact: true }).click()
    await expect(cookieInput).toHaveValue('••••••已设置')
    // 防浏览器自动填充（登录密码 Admin@12345 不得误填进 Cookie 输入框）：初始只读 + new-password
    await expect(cookieInput).toHaveAttribute('readonly')
    await expect(cookieInput).toHaveAttribute('autocomplete', 'new-password')

    // 重新进入必须读取当前状态；失败不能沿用旧成功或显示成“未设置”。
    await page.reload()
    await expect(settingsRegion.getByText('服务暂时不可用，请稍后重试', { exact: true })).toBeVisible()
    await expect(cookieInput).toHaveCount(0)
    await page.getByRole('button', { name: '重试', exact: true }).click()
    await expect(page.getByText('已存密文无法解密，请检查主密钥或输入新值后保存', { exact: true })).toBeVisible()
    await expect(cookieInput).toHaveAttribute('readonly')
    await expect(cookieInput).toHaveAttribute('autocomplete', 'new-password')
    // fill 要求元素可编辑：先点击聚焦（触发 focus 移除 readonly，模拟真实用户先点击再输入）
    await cookieInput.click()
    await expect(cookieInput).not.toHaveAttribute('readonly')
    await cookieInput.fill('e2e-ui-only-cookie')
    await expect(page.getByRole('button', { name: '保存并生效', exact: true })).toBeEnabled()
    expect(settingsCalls).toBe(4)
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
