import { expect, test } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'

const activeTask = {
  id: 'e2e-running-task',
  task_type: 'update',
  status: 'running',
  progress: 0.5,
  message: '自动轮询测试',
  params: {},
  trigger_source: 'manual',
  capability: { can_cancel: false, can_resume: false },
  created_at: '2026-07-20 10:00:00',
  updated_at: '2026-07-20 10:01:00',
}

const resumableFailedTask = {
  ...activeTask,
  id: 'e2e-resumable-failed-task',
  status: 'failed',
  message: '操作列最低宽度验证',
  capability: {
    can_cancel: false,
    can_resume: true,
    checkpoint: { phase: 'daily_bar' },
  },
}

test.describe('任务中心轮询', () => {
  test('多动作列自动扩展并保留两个直接操作入口', async ({ page, request }) => {
    await loginAsDebugUser(page, request, 'debug_system')

    await page.route('**/api/data/tasks?**', async (route) => {
      const url = new URL(route.request().url())
      if (!url.searchParams.has('page')) {
        await route.continue()
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0,
          msg: 'ok',
          data: { tasks: [resumableFailedTask], total: 1 },
        }),
      })
    })

    await page.goto('/data/ingest')
    const row = page.getByRole('row').filter({ hasText: '操作列最低宽度验证' })
    await expect(row.getByRole('button', { name: '重试未完成项', exact: true })).toBeVisible()
    await expect(row.getByRole('button', { name: '日志', exact: true })).toBeVisible()
    await expect(row.getByRole('button', { name: '更多', exact: true })).toHaveCount(0)

    const geometry = await row.locator('.app-row-actions').evaluate((element) => {
      const group = element.getBoundingClientRect()
      const cell = element.closest('td')?.getBoundingClientRect()
      return {
        cellWidth: cell?.width ?? 0,
        fitsCell: Boolean(cell && group.left >= cell.left && group.right <= cell.right),
      }
    })
    expect(geometry.cellWidth).toBeGreaterThan(144)
    expect(geometry.fitsCell).toBe(true)
  })

  test('运行中任务自动刷新时不重复显示加载遮罩', async ({ page, request }) => {
    await loginAsDebugUser(page, request, 'debug_system')

    let taskListCalls = 0
    let releasePolling!: () => void

    await page.route('**/api/data/tasks?**', async (route) => {
      const url = new URL(route.request().url())
      // 顶栏也会读取任务摘要；这里只控制带分页参数的任务中心列表请求。
      if (!url.searchParams.has('page')) {
        await route.continue()
        return
      }
      taskListCalls += 1
      if (taskListCalls === 2) {
        await new Promise<void>((resolve) => { releasePolling = resolve })
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, msg: 'ok', data: { tasks: [activeTask], total: 1 } }),
      })
    })

    await page.goto('/data/ingest')
    const taskPanel = page.getByTestId('task-center-panel')
    await expect(taskPanel.getByText('自动轮询测试')).toBeVisible()
    await expect(taskPanel.locator('.el-loading-mask')).toBeHidden()

    await expect.poll(() => taskListCalls).toBe(2)
    await expect(taskPanel.locator('.el-loading-mask')).toBeHidden()

    releasePolling()
  })

  test('实时日志抽屉按页面内容区响应式增长并保持宽度上下限', async ({ page, request }) => {
    await loginAsDebugUser(page, request, 'debug_system')

    await page.route('**/api/data/tasks?**', async (route) => {
      const url = new URL(route.request().url())
      if (!url.searchParams.has('page')) {
        await route.continue()
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, msg: 'ok', data: { tasks: [activeTask], total: 1 } }),
      })
    })
    await page.route('**/api/data/tasks/e2e-running-task', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, msg: 'ok', data: activeTask }),
      })
    })
    await page.route('**/api/data/tasks/e2e-running-task/logs?**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0,
          msg: 'ok',
          data: {
            logs: [{
              seq: 1,
              ts: '2026-07-20 10:01:00',
              level: 'info',
              message: '响应式宽抽屉验证日志',
            }],
          },
        }),
      })
    })

    await page.goto('/data/ingest')
    const taskPanel = page.getByTestId('task-center-panel')
    await expect(taskPanel.getByText('自动轮询测试')).toBeVisible()
    await taskPanel.getByRole('button', { name: '日志', exact: true }).click()

    const pageRoot = page.locator('.v-page')
    const drawer = page.getByTestId('task-log-drawer')
    await expect(drawer).toBeVisible()
    await expect(drawer.getByText('响应式宽抽屉验证日志')).toBeVisible()

    const expectedWidth = async () => {
      const pageWidth = await pageRoot.evaluate((element) => element.getBoundingClientRect().width)
      return Math.min(760, Math.max(560, pageWidth * 0.46))
    }
    const actualWidth = () =>
      drawer.evaluate((element) => element.getBoundingClientRect().width)

    await expect.poll(actualWidth).toBeCloseTo(await expectedWidth(), 0)
    const initialWidth = await actualWidth()

    await page.setViewportSize({ width: 1920, height: 900 })
    await expect.poll(actualWidth).toBeCloseTo(await expectedWidth(), 0)
    expect(await actualWidth()).toBeGreaterThan(initialWidth)
    expect(await actualWidth()).toBeLessThanOrEqual(761)
  })
})
