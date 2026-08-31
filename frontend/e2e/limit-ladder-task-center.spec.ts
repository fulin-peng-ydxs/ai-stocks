import { expect, test } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'

const ladderTask = {
  id: 'e2e-limit-ladder-task',
  task_type: 'limit_ladder_recompute',
  status: 'done',
  progress: 1,
  message: '2026-08-28 连板天梯快照完成',
  params: { trade_date: '2026-08-28' },
  result: {
    trade_date: '2026-08-28',
    snapshot_id: 'snapshot-e2e',
    snapshot_status: 'valid',
    coverage: {
      pool_count: 5200,
      valid_bar_count: 5198,
      confirmed_suspension_count: 2,
      missing_count: 0,
      invalid_bar_count: 0,
      unsupported_rule_count: 0,
      ingest_terminal_status: 'success',
    },
  },
  trigger_source: 'system',
  job_name: '自动首算',
  capability: { can_cancel: false, can_resume: false },
  created_at: '2026-08-28 18:00:00',
  updated_at: '2026-08-28 18:01:00',
}

const interruptedTask = {
  ...ladderTask,
  id: 'e2e-limit-ladder-interrupted',
  status: 'interrupted',
  progress: 0.42,
  message: '服务重启后任务已中断，最后成功快照仍可读取',
  result: {
    ...ladderTask.result,
    snapshot_status: 'interrupted',
  },
  updated_at: '2026-08-28 18:00:30',
}

test('连板天梯任务可筛选并在日志抽屉展示快照与 coverage 摘要', async ({
  page,
  request,
}, testInfo) => {
  const consoleIssues = collectConsoleIssues(page)
  await loginAsDebugUser(page, request, 'debug_system')
  let requestedTaskType: string | null = null
  let requestedStatus: string | null = null

  await page.route('**/api/data/tasks?**', async (route) => {
    const url = new URL(route.request().url())
    if (!url.searchParams.has('page')) {
      await route.continue()
      return
    }
    requestedTaskType = url.searchParams.get('task_type')
    requestedStatus = url.searchParams.get('status')
    const tasks = url.searchParams.get('status') === 'interrupted'
      ? [interruptedTask]
      : [ladderTask]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, msg: 'ok', data: { tasks, total: 1 } }),
    })
  })
  await page.route('**/api/data/tasks/e2e-limit-ladder-task', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, msg: 'ok', data: ladderTask }),
    })
  })
  await page.route('**/api/data/tasks/e2e-limit-ladder-task/logs?**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: { logs: [{ seq: 1, ts: '2026-08-28 18:01:00', level: 'info', message: '快照已原子切换' }] },
      }),
    })
  })
  await page.route('**/api/data/tasks/e2e-limit-ladder-interrupted', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, msg: 'ok', data: interruptedTask }),
    })
  })
  await page.route('**/api/data/tasks/e2e-limit-ladder-interrupted/logs?**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: { logs: [{ seq: 1, ts: '2026-08-28 18:00:30', level: 'warning', message: '重启对账标记 interrupted' }] },
      }),
    })
  })

  await page.goto('/data/ingest')
  await page.getByTestId('task-type-filter').click()
  await page.getByRole('option', { name: '连板天梯重算' }).click()
  await expect.poll(() => requestedTaskType).toBe('limit_ladder_recompute')
  await page.getByTestId('task-status-filter').click()
  await page.getByRole('option', { name: '已完成', exact: true }).click()
  await expect.poll(() => requestedStatus).toBe('done')

  const taskPanel = page.getByTestId('task-center-panel')
  await expect(taskPanel.getByText(/连板天梯重算.*2026-08-28/)).toBeVisible()
  await expect(taskPanel.getByText(/系统.*自动首算/)).toBeVisible()
  await taskPanel.getByRole('button', { name: '日志', exact: true }).click()

  const result = page.getByTestId('limit-ladder-task-result')
  await expect(result).toBeVisible()
  await expect(result.getByText('snapshot-e2e')).toBeVisible()
  await expect(result.getByText('5200')).toBeVisible()
  await expect(result.getByText('success')).toBeVisible()
  await expect(page.getByText('快照已原子切换')).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(page.getByTestId('task-log-drawer')).toBeHidden()
  await page.getByTestId('task-status-filter').click()
  await page.getByRole('option', { name: '已中断', exact: true }).click()
  await expect.poll(() => requestedStatus).toBe('interrupted')
  await expect(taskPanel.getByText('服务重启后任务已中断，最后成功快照仍可读取')).toBeVisible()
  await expect(taskPanel.getByText('已中断', { exact: true })).toBeVisible()
  await taskPanel.getByRole('button', { name: '日志', exact: true }).click()
  await expect(page.getByTestId('limit-ladder-task-result')).toContainText('interrupted')
  await expect(page.getByText('重启对账标记 interrupted')).toBeVisible()

  const screenshotPath = testInfo.outputPath('limit-ladder-task-center.png')
  await page.screenshot({ path: screenshotPath, fullPage: true })
  await testInfo.attach('limit-ladder-task-center', {
    path: screenshotPath,
    contentType: 'image/png',
  })
  expect(consoleIssues).toEqual([])
})
