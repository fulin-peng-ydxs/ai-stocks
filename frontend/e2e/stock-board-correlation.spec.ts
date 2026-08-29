import { expect, test, type Page } from '@playwright/test'

import type { StockBasic } from '../src/api/stocks'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { DEFAULT_E2E_API_URL } from './helpers/e2e-backend-health.mjs'
import { openPageAndWaitForHeading } from './helpers/navigation'
import { requireSeededCorrelationStocks } from './helpers/stockBoardCorrelation'

const API_URL = process.env.E2E_API_URL || DEFAULT_E2E_API_URL

async function resetColumns(page: Page) {
  await page.getByTestId('page-settings-trigger').click()
  const drawer = page.getByTestId('page-settings-drawer')
  await drawer.getByTestId('page-settings-reset').click()
  await drawer.getByRole('button', { name: '关闭页面设置' }).click()
}

async function ensureRelatedColumnsVisible(page: Page, slotId: 'table' | 'result') {
  await page.getByTestId('page-settings-trigger').click()
  const drawer = page.getByTestId('page-settings-drawer')
  const industrySwitch = drawer.getByTestId(
    `component-${slotId}-hiddenColumns-relatedIndustry-switch`,
  )
  if (!await industrySwitch.isVisible()) {
    await drawer.getByRole('button', { name: '组件设置', exact: true }).click()
  }
  for (const key of ['relatedIndustry', 'relatedConcept']) {
    const columnSwitch = drawer.getByTestId(`component-${slotId}-hiddenColumns-${key}-switch`)
    await expect(columnSwitch).toBeVisible()
    const checkbox = columnSwitch.locator('input[type="checkbox"]')
    if (!await checkbox.isChecked()) await columnSwitch.click()
    await expect(checkbox).toBeChecked()
  }
  await drawer.getByRole('button', { name: '关闭页面设置' }).click()
}

test.describe('个股走势关联板块 T10 页面验收', () => {
  test('三个业务页面展示真实夹具结果，并支持说明和列显隐', async ({
    page,
    request,
  }) => {
    test.setTimeout(90_000)
    const consoleIssues = collectConsoleIssues(page)
    const auth = await loginAsDebugUser(page, request, 'debug_system')
    const fixture = await requireSeededCorrelationStocks(request, auth.accessToken)
    const headers = { authorization: `Bearer ${auth.accessToken}` }

    await openPageAndWaitForHeading(page, '/stocks', '个股查询')
    await resetColumns(page)
    await ensureRelatedColumnsVisible(page, 'table')
    await page.getByPlaceholder('代码 / 名称').fill('E2E相关-股票')
    await page.getByPlaceholder('代码 / 名称').press('Enter')
    await expect(page.getByRole('columnheader', { name: '走势行业' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '走势概念' })).toBeVisible()
    const industry = page.getByRole('link', { name: 'E2E相关-行业冠军' }).first()
    await expect(industry).toBeVisible()
    await industry.focus()
    await expect(page.getByLabel('E2E相关-行业冠军相关性说明').first()).toContainText('20 日')
    await page.keyboard.press('Escape')

    await page.getByTestId('page-settings-trigger').click()
    const stockDrawer = page.getByTestId('page-settings-drawer')
    const industrySwitch = stockDrawer.getByTestId(
      'component-table-hiddenColumns-relatedIndustry-switch',
    )
    if (!await industrySwitch.isVisible()) {
      await stockDrawer.getByRole('button', { name: '组件设置', exact: true }).click()
    }
    await industrySwitch.click()
    await stockDrawer.getByRole('button', { name: '关闭页面设置' }).click()
    await expect(page.getByRole('columnheader', { name: '走势行业' })).toHaveCount(0)
    await ensureRelatedColumnsVisible(page, 'table')

    const boardProfilesResponse = await request.get(`${API_URL}/board/profiles`, {
      headers,
      params: { source: 'mine' },
    })
    expect(boardProfilesResponse.ok()).toBe(true)
    const boardProfilesBody = await boardProfilesResponse.json()
    const boardProfile = boardProfilesBody.data.find(
      (item: { id: string }) => item.id === 'e2e_sbc_score_profile',
    )
    expect(boardProfile).toBeTruthy()
    const boardRunResponse = await request.post(`${API_URL}/board/run`, {
      headers,
      data: {
        profile_ref: boardProfile.profile_ref,
        run_date: fixture.targetDate,
        top: fixture.stocks.length,
      },
    })
    expect(boardRunResponse.ok()).toBe(true)
    const boardRunBody = await boardRunResponse.json()
    expect(boardRunBody.data.list).toHaveLength(fixture.stocks.length)
    expect(boardRunBody.data.list.every((row: StockBasic) => row.related_boards?.industry)).toBe(true)

    await openPageAndWaitForHeading(page, '/board', '每日榜单')
    await resetColumns(page)
    await ensureRelatedColumnsVisible(page, 'table')
    await expect(page.getByTestId('board-profile-select')).toContainText('E2E 关联展示评分方案')
    await expect(page.getByRole('columnheader', { name: '走势行业' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'E2E相关-概念冠军' }).first()).toBeVisible()

    const screenProfilesResponse = await request.get(`${API_URL}/profiles`, {
      headers,
      params: { source: 'mine' },
    })
    expect(screenProfilesResponse.ok()).toBe(true)
    const screenProfilesBody = await screenProfilesResponse.json()
    expect(screenProfilesBody.data.some(
      (item: { id: string }) => item.id === 'e2e_sbc_screen_profile',
    )).toBe(true)

    await openPageAndWaitForHeading(page, '/screen', '策略筛选')
    await resetColumns(page)
    await ensureRelatedColumnsVisible(page, 'result')
    await expect(page.getByTestId('screen-profile-select')).toContainText('E2E 关联展示筛选方案')
    const runButton = page.getByRole('button', { name: '运行筛选', exact: true })
    await expect(runButton).toBeEnabled()
    await runButton.click()
    await expect(page.getByRole('columnheader', { name: '走势行业' })).toBeVisible({
      timeout: 30_000,
    })
    await expect(page.getByRole('link', { name: 'E2E相关-行业冠军' }).first()).toBeVisible()
    expect(consoleIssues).toEqual([])
  })

  test('历史日期降级且最小权限账号不能跳转板块', async ({ page, request }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium-standard', '权限和历史态仅在标准视口执行')
    const auth = await loginAsDebugUser(page, request, 'debug_stocks_only')
    const fixture = await requireSeededCorrelationStocks(request, auth.accessToken)

    await openPageAndWaitForHeading(page, '/stocks', '个股查询')
    await resetColumns(page)
    await page.getByPlaceholder('代码 / 名称').fill('E2E相关-股票')
    await page.getByPlaceholder('代码 / 名称').press('Enter')
    await expect(page.getByText('E2E相关-行业冠军', { exact: true }).first()).toBeVisible()
    await expect(page.getByRole('link', { name: 'E2E相关-行业冠军' })).toHaveCount(0)

    const target = new Date(`${fixture.targetDate}T00:00:00`)
    target.setDate(target.getDate() - 1)
    const previousDate = target.toISOString().slice(0, 10)
    const historyResponse = await request.get(`${API_URL}/stocks`, {
      headers: { authorization: `Bearer ${auth.accessToken}` },
      params: { q: 'E2E相关-股票', trade_date: previousDate, page: 1, size: 20 },
    })
    expect(historyResponse.ok()).toBe(true)
    const historyBody = await historyResponse.json()
    expect(historyBody.data.list).toHaveLength(4)
    expect(historyBody.data.list.every((row: StockBasic) => (
      row.related_boards?.unavailable_reason === 'as_of_mismatch'
    ))).toBe(true)
    await page.route(/\/api\/stocks(?:\?|$)/, async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify(historyBody),
      })
    })
    await page.getByPlaceholder('代码 / 名称').press('Enter')
    await expect(page.getByLabel('未保留该历史日期的相关性结果').first()).toBeVisible()
  })

  test('管理员读取真实调度和任务结果，立即执行入口不污染任务表', async ({
    page,
    request,
  }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium-standard', '系统链路仅在标准视口执行')
    const consoleIssues = collectConsoleIssues(page)
    const auth = await loginAsDebugUser(page, request, 'debug_system')
    const fixture = await requireSeededCorrelationStocks(request, auth.accessToken)

    let runRequested = false
    await page.route('**/api/data/schedules/e2e_sbc_job/run', async (route) => {
      runRequested = true
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, msg: 'ok', data: { task_id: 'e2e_sbc_preview' } }),
      })
    })
    await openPageAndWaitForHeading(page, '/data/schedule', '任务调度')
    const jobRow = page.getByRole('row').filter({ hasText: 'E2E相关-盘后计算' })
    await expect(jobRow).toContainText('个股走势关联板块·指定 2 只')
    await jobRow.getByRole('button', { name: '编辑', exact: true }).click()
    await expect(page.getByTestId('schedule-correlation-codes')).toContainText('997701.SZ')
    await page.getByTestId('schedule-dialog').getByRole('button', { name: '取消' }).click()
    await jobRow.getByRole('button', { name: '立即执行', exact: true }).click()
    await expect(page.getByText(/立即执行一次「E2E相关-盘后计算」/)).toBeVisible()
    await page.getByRole('button', { name: '确定', exact: true }).click()
    await expect.poll(() => runRequested).toBe(true)
    await expect(page).toHaveURL(/\/data\/ingest$/)
    await expect(page.getByRole('dialog', { name: '立即执行' })).toBeHidden()
    await page.getByTestId('page-settings-trigger').click()
    const settingsDrawer = page.getByTestId('page-settings-drawer')
    await settingsDrawer.getByTestId('task-status-default-all').click()
    await settingsDrawer.getByRole('button', { name: '关闭页面设置' }).click()
    const taskResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'GET'
      && new URL(response.url()).pathname === '/api/data/tasks'
    ))
    await page.getByRole('button', { name: '刷新', exact: true }).first().click()
    const taskResponse = await taskResponsePromise
    expect(taskResponse.ok()).toBe(true)
    const taskBody = await taskResponse.json()
    expect(taskBody.data.tasks.some(
      (task: { id: string }) => task.id === 'e2e_sbc_task',
    )).toBe(true)

    const taskPanel = page.getByTestId('task-center-panel')
    const taskRow = taskPanel.getByRole('row').filter({ hasText: 'E2E相关-盘后计算' })
    await expect(taskRow).toContainText('个股走势关联板块')
    await taskRow.getByRole('button', { name: '日志', exact: true }).click()
    await expect(page.getByTestId('correlation-task-result')).toContainText(fixture.targetDate)
    await expect(page.getByTestId('correlation-task-result')).toContainText('候选关系')
    await expect(page.getByTestId('correlation-task-result')).toContainText('8')
    await expect(page.getByTestId('task-log-drawer')).toContainText('原子切换完成')
    expect(consoleIssues).toEqual([])
  })
})
