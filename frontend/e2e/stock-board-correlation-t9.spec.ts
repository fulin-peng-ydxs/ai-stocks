import { expect, test } from '@playwright/test'

import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { openPageAndWaitForHeading } from './helpers/navigation'

const baseJob = {
  id: 'e2e-correlation-existing',
  name: 'E2E 关联板块存量调度',
  task_type: 'stock_board_correlation',
  params: { codes: ['000001.SZ', '600000.SH'], force: true },
  freq_type: 'daily',
  freq_config: { time: '15:30' },
  trigger_mode: 'time',
  dependency_job_id: null,
  dependency_condition: null,
  dependency_delay: { value: 0, unit: 'minute' },
  retry_config: {
    enabled: false,
    condition: 'failure',
    delay: { value: 5, unit: 'minute' },
    max_retries: 1,
  },
  trading_day_only: true,
  enabled: true,
  last_run_at: null,
  last_task_id: null,
  created_at: '2026-08-29 20:00:00',
  updated_at: '2026-08-29 20:00:00',
  freq_text: '每日 15:30',
  trigger_text: '每日 15:30',
  waiting_trigger_count: 0,
  next_run_time: '2026-08-30 15:30:00',
}

test.describe('个股走势关联板块 T9 页面闭环', () => {
  test('管理员可回显、取消并保存调度，失败时保留表单', async ({ page, request }) => {
    const consoleIssues = collectConsoleIssues(page, { allowedHttpStatuses: [400] })
    await loginAsDebugUser(page, request, 'debug_system')
    let postAttempts = 0
    let submitted: Record<string, any> | null = null

    await page.route(/\/api\/data\/schedules(?:\/[^/?]+)?(?:\?.*)?$/, async (route) => {
      const method = route.request().method()
      if (method === 'POST') {
        postAttempts += 1
        submitted = route.request().postDataJSON()
        if (postAttempts === 1) {
          return route.fulfill({
            status: 400,
            contentType: 'application/json',
            body: JSON.stringify({ code: 4000, msg: 'E2E 股票代码不存在', data: null }),
          })
        }
        return route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify({ code: 0, msg: 'ok', data: { id: 'e2e-correlation-created' } }),
        })
      }
      const jobs = [baseJob]
      if (submitted && postAttempts > 1) {
        jobs.push({
          ...baseJob,
          id: 'e2e-correlation-created',
          name: String(submitted.name),
          params: submitted.params as { codes: string[]; force: boolean },
          enabled: Boolean(submitted.enabled),
        })
      }
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0,
          msg: 'ok',
          data: {
            jobs,
            task_types: ['stock_ingest', 'board', 'verify', 'stock_board_correlation'],
            quality_issue_types: [],
          },
        }),
      })
    })

    await openPageAndWaitForHeading(page, '/data/schedule', '任务调度')

    const existingRow = page.getByRole('row').filter({ hasText: baseJob.name })
    await expect(existingRow).toContainText('个股走势关联板块·指定 2 只·强制重算')
    await existingRow.getByRole('button', { name: '编辑', exact: true }).click()
    const editDialog = page.getByTestId('schedule-dialog')
    await expect(editDialog).toContainText('编辑调度任务')
    await expect(page.getByTestId('schedule-correlation-scope-selected')).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await expect(page.getByTestId('schedule-correlation-codes')).toContainText('000001.SZ')
    await expect(page.getByTestId('schedule-correlation-codes')).toContainText('+ 1')
    await expect(page.getByTestId('schedule-correlation-force').getByRole('switch')).toBeChecked()
    await editDialog.getByRole('button', { name: '取消', exact: true }).click()
    await expect(editDialog).toBeHidden()

    await page.getByTestId('schedule-create').click()
    const createDialog = page.getByTestId('schedule-dialog')
    await page.getByTestId('schedule-name').fill('E2E 关联板块新建调度')
    await page.getByTestId('schedule-task-type').click()
    await page.getByRole('option', { name: '个股走势关联板块', exact: true }).click()
    await page.getByTestId('schedule-correlation-scope-selected').click()
    await page.getByTestId('schedule-save').click()
    await expect(page.getByText('指定股票范围时请至少选择一只股票')).toBeVisible()
    expect(postAttempts).toBe(0)

    await page.getByTestId('schedule-correlation-codes').evaluate((element) => {
      const clipboard = new DataTransfer()
      clipboard.setData('text', '000001.sz, 600000.sh\n000001.SZ')
      element.dispatchEvent(new ClipboardEvent('paste', {
        bubbles: true,
        cancelable: true,
        clipboardData: clipboard,
      }))
    })
    await page.getByTestId('schedule-correlation-force').click()
    await page.getByTestId('schedule-save').click()
    await expect(page.getByText('E2E 股票代码不存在')).toBeVisible()
    await expect(createDialog).toBeVisible()
    await expect(page.getByTestId('schedule-name')).toHaveValue('E2E 关联板块新建调度')
    await expect(page.getByTestId('schedule-correlation-codes')).toContainText('000001.SZ')
    await expect(page.getByTestId('schedule-correlation-codes')).toContainText('+ 1')
    await expect(page.getByTestId('schedule-correlation-force').getByRole('switch')).toBeChecked()

    await page.getByTestId('schedule-save').click()
    await expect(createDialog).toBeHidden()
    expect(postAttempts).toBe(2)
    expect(submitted?.task_type).toBe('stock_board_correlation')
    expect(submitted?.params).toEqual({ codes: ['000001.SZ', '600000.SH'], force: true })
    const createdRow = page.getByRole('row').filter({ hasText: 'E2E 关联板块新建调度' })
    await expect(createdRow).toContainText('个股走势关联板块·指定 2 只·强制重算')
    expect(consoleIssues).toEqual([])
  })

  test('任务中心展示关联计算阶段与终态统计', async ({ page, request }) => {
    const consoleIssues = collectConsoleIssues(page)
    await loginAsDebugUser(page, request, 'debug_system')
    const task = {
      id: 'e2e-correlation-task',
      task_type: 'stock_board_correlation',
      status: 'done',
      progress: 1,
      message: '关联板块计算完成',
      params: { codes: ['000001.SZ', '600000.SH'], force: true },
      trigger_source: 'scheduled',
      job_name: '盘后关联板块',
      capability: {
        can_cancel: false,
        can_resume: false,
        current_phase: 'switch',
        current_item: '正式表',
      },
      result: {
        target_date: '2026-08-28',
        target_stock_count: 2,
        candidate_relation_count: 17,
        industry_champion_count: 2,
        concept_champion_count: 1,
        empty_result_count: 1,
        fallback_count: 1,
        skipped_count: 0,
        failed_count: 0,
        calculation_seconds: 1.25,
        write_seconds: 0.08,
        benchmark_counts: { '000001.SH': 1, '399001.SZ': 1 },
        switched: true,
      },
      created_at: '2026-08-29 20:00:00',
      updated_at: '2026-08-29 20:00:02',
    }

    await page.route('**/api/data/tasks/e2e-correlation-task/logs?**', async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0,
          msg: 'ok',
          data: {
            logs: [{
              seq: 1,
              ts: '2026-08-29 20:00:02',
              level: 'info',
              message: '原子切换完成',
            }],
          },
        }),
      })
    })
    await page.route('**/api/data/tasks/e2e-correlation-task', async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, msg: 'ok', data: task }),
      })
    })
    await page.route('**/api/data/tasks?**', async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, msg: 'ok', data: { tasks: [task], total: 1 } }),
      })
    })

    await openPageAndWaitForHeading(page, '/data/ingest', '数据采集')
    const taskPanel = page.getByTestId('task-center-panel')
    const row = taskPanel.getByRole('row').filter({ hasText: '盘后关联板块' })
    await expect(row).toContainText('个股走势关联板块·指定 2 只·强制重算')
    await row.getByRole('button', { name: '日志', exact: true }).click()

    await expect(page.getByTestId('task-log-drawer')).toContainText('原子切换 · 正式表')
    const result = page.getByTestId('correlation-task-result')
    await expect(result).toContainText('2026-08-28')
    await expect(result).toContainText('候选关系')
    await expect(result).toContainText('17')
    await expect(result).toContainText('000001.SH 1 · 399001.SZ 1')
    await expect(result).toContainText('已原子切换')
    await expect(page.getByTestId('task-log-drawer')).toContainText('原子切换完成')
    expect(consoleIssues).toEqual([])
  })

  test('普通用户不能进入系统调度和任务中心', async ({ page, request }) => {
    await loginAsDebugUser(page, request, 'debug_normal')
    await page.goto('/data/schedule')
    await expect(page).not.toHaveURL(/\/data\/schedule/)
    await expect(page.getByTestId('schedule-create')).toHaveCount(0)

    await page.goto('/data/ingest')
    await expect(page).not.toHaveURL(/\/data\/ingest/)
    await expect(page.getByTestId('task-center-panel')).toHaveCount(0)
  })
})
