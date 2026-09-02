import { expect, test } from '@playwright/test'

import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { openPageAndWaitForHeading } from './helpers/navigation'

test.describe('个股一体化采集', () => {
  test('手动入口统一配置方案、股票范围并提交 stock_ingest', async ({ page, request }) => {
    const consoleIssues = collectConsoleIssues(page)
    await loginAsDebugUser(page, request, 'debug_system')
    let submitted: Record<string, any> | null = null

    await page.route('**/api/data/stock-quality?**', async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0, msg: 'ok', data: {
            total: 1, page: 1, size: 30, latest_trade_date: '2026-08-25',
            list: [{ code: '600000.SH', name: '浦发银行' }],
          },
        }),
      })
    })
    await page.route('**/api/data/tasks', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      submitted = route.request().postDataJSON()
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, msg: 'ok', data: { task_id: 'e2e_stock_task' } }),
      })
    })
    await page.route('**/api/data/tasks?**', async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, msg: 'ok', data: { tasks: [], total: 0 } }),
      })
    })
    await page.route('**/api/data/tasks/e2e_stock_task', async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0, msg: 'ok', data: {
            id: 'e2e_stock_task', task_type: 'stock_ingest', status: 'done', progress: 1,
            message: '完成', params: { recipe: 'daily_update', codes: ['600000.SH'] },
            created_at: '2026-08-25 16:00:00', updated_at: '2026-08-25 16:00:01',
          },
        }),
      })
    })
    await page.route('**/api/data/tasks/e2e_stock_task/logs?**', async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, msg: 'ok', data: { logs: [] } }),
      })
    })

    await openPageAndWaitForHeading(page, '/data/ingest', '数据采集')
    const workspaceTabs = page.getByTestId('ingest-workspace-tabs')
    await expect(workspaceTabs).toContainText('任务中心')
    await expect(workspaceTabs).toContainText('采集日志')
    const taskToolbar = page.getByTestId('ingest-tasks-toolbar')
    await expect(taskToolbar.getByTestId('task-type-filter')).toBeVisible()
    await expect(taskToolbar.getByTestId('task-status-filter')).toBeVisible()
    await expect(taskToolbar).toContainText('点击任务行查看运行日志')
    await expect(taskToolbar.getByText('任务中心', { exact: true })).toHaveCount(0)
    await page.getByRole('tab', { name: '采集日志' }).click()
    await expect(page.getByTestId('ingest-log-panel')).toBeVisible()
    const logToolbar = page.getByTestId('ingest-logs-toolbar')
    await expect(logToolbar).toContainText('失败行可见原因')
    await expect(logToolbar.getByText('采集日志', { exact: true })).toHaveCount(0)
    await page.getByRole('tab', { name: '任务中心' }).click()
    await expect(page.getByTestId('task-center-panel')).toBeVisible()
    await expect(page.getByRole('button', { name: '配置采集' })).toHaveCount(0)

    const dialog = page.getByTestId('ingest-options-dialog')
    await page.getByTestId('manual-board-ingest').click()
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('板块采集')
    await expect(dialog.getByTestId('ingest-board-mode-update')).toHaveAttribute('aria-pressed', 'true')
    const boardDialogBox = await dialog.boundingBox()
    const viewport = page.viewportSize()
    expect(boardDialogBox).not.toBeNull()
    expect(viewport).not.toBeNull()
    expect(boardDialogBox!.y).toBeGreaterThanOrEqual(0)
    expect(boardDialogBox!.y + boardDialogBox!.height).toBeLessThanOrEqual(viewport!.height)
    expect(Math.abs(boardDialogBox!.y + boardDialogBox!.height / 2 - viewport!.height / 2))
      .toBeLessThanOrEqual(16)
    expect(await dialog.evaluate((element) => getComputedStyle(element).backgroundColor))
      .not.toBe('rgba(0, 0, 0, 0)')
    await dialog.getByRole('button', { name: '取消' }).click()

    await page.getByTestId('manual-stock-ingest').click()
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('个股采集')
    const stockDialogBox = await dialog.boundingBox()
    expect(stockDialogBox).not.toBeNull()
    expect(stockDialogBox!.y).toBeGreaterThanOrEqual(0)
    expect(stockDialogBox!.y + stockDialogBox!.height).toBeLessThanOrEqual(viewport!.height)
    expect(Math.abs(stockDialogBox!.y + stockDialogBox!.height / 2 - viewport!.height / 2))
      .toBeLessThanOrEqual(16)
    await dialog.getByTestId('ingest-stock-scope-selected').click()
    const codes = dialog.getByTestId('ingest-stock-codes')
    await codes.click()
    await codes.locator('input').fill('浦发')
    await page.getByRole('option', { name: '600000.SH 浦发银行' }).click()
    await expect(dialog).toContainText('将执行：日常同步 · 1 只指定股票')
    await dialog.getByTestId('ingest-execute-submit').click()

    await expect.poll(() => submitted).toEqual({
      task_type: 'stock_ingest',
      params: { recipe: 'daily_update', codes: ['600000.SH'] },
    })
    await expect(page.getByTestId('task-log-drawer')).toBeVisible()
    await expect(page.getByRole('button', { name: '查看数据概览' })).toBeVisible()
    await expect(page.getByRole('button', { name: '查看数据质量' })).toBeVisible()
    expect(consoleIssues).toEqual([])
  })

  test('新建调度默认使用统一任务模型', async ({ page, request }) => {
    const consoleIssues = collectConsoleIssues(page)
    await loginAsDebugUser(page, request, 'debug_system')
    const jobName = `E2E 个股基础资料刷新 ${Date.now()}`
    let submitted: Record<string, any> | null = null

    await page.route('**/api/data/schedules', async (route) => {
      if (route.request().method() === 'POST') {
        submitted = route.request().postDataJSON()
        return route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify({ code: 0, msg: 'ok', data: { id: 'e2e_stock_schedule' } }),
        })
      }
      const jobs = submitted ? [{
        id: 'e2e_stock_schedule', ...submitted,
        last_run_at: null, last_task_id: null,
        created_at: '2026-08-25 16:00:00', updated_at: '2026-08-25 16:00:00',
        freq_text: '每日 15:30', trigger_text: '按时间', waiting_trigger_count: 0,
        next_run_time: null,
      }] : []
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0, msg: 'ok', data: {
            jobs, task_types: ['stock_ingest', 'board', 'verify'], quality_issue_types: [],
          },
        }),
      })
    })

    await openPageAndWaitForHeading(page, '/data/schedule', '任务调度')
    await page.getByTestId('schedule-create').click()
    await page.getByTestId('schedule-name').fill(jobName)
    await expect(page.getByTestId('schedule-task-type')).toContainText('个股采集')
    await page.getByTestId('schedule-stock-recipe').click()
    await page.getByRole('option', { name: '基础资料刷新' }).click()
    const summaryBox = await page.getByTestId('schedule-stock-summary').boundingBox()
    const dividerBox = await page.getByTestId('schedule-trigger-divider').boundingBox()
    expect(summaryBox).not.toBeNull()
    expect(dividerBox).not.toBeNull()
    expect(summaryBox!.y + summaryBox!.height).toBeLessThanOrEqual(dividerBox!.y)
    await page.getByTestId('schedule-enabled').click()
    await page.getByTestId('schedule-save').click()

    const row = page.getByRole('row').filter({ hasText: jobName })
    await expect(row).toContainText('个股采集·基础资料刷新')
    expect(submitted?.task_type).toBe('stock_ingest')
    expect(submitted?.params).toEqual({ recipe: 'basic_refresh' })
    expect(submitted?.enabled).toBe(false)
    expect(consoleIssues).toEqual([])
  })
})
