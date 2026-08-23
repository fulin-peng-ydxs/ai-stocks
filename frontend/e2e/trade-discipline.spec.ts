import { expect, test, type Page } from '@playwright/test'

import {
  authenticateDebugUser,
  installAuthSnapshot,
  type E2EAuthSnapshot,
} from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import {
  requireTradeDisciplineFixture,
  TRADE_DISCIPLINE_FIXTURE,
} from './helpers/tradeDiscipline'

async function useAuth(page: Page, auth: E2EAuthSnapshot): Promise<void> {
  await installAuthSnapshot(page, auth)
  await page.goto('/trade-discipline')
}

async function chooseDialog(page: Page, label: string): Promise<void> {
  await page.getByRole('dialog').getByRole('button', { name: label, exact: true }).click()
}

async function expectHistoryLayout(page: Page): Promise<void> {
  const geometry = await page.evaluate(() => {
    const panel = document.querySelector<HTMLElement>('.history-panel')
    const workspace = document.querySelector<HTMLElement>('.history-workspace')
    const filterCard = document.querySelector<HTMLElement>('.history-filter-card .el-card__body')
    const filters = document.querySelector<HTMLElement>('.history-filters')
    const top = (selector: string) => document.querySelector<HTMLElement>(selector)?.getBoundingClientRect().top ?? 0
    return {
      panelWidth: panel?.getBoundingClientRect().width ?? 0,
      workspaceWidth: workspace?.getBoundingClientRect().width ?? 0,
      filterCardLeft: filterCard?.getBoundingClientRect().left ?? 0,
      filterCardRight: filterCard?.getBoundingClientRect().right ?? 0,
      filtersLeft: filters?.getBoundingClientRect().left ?? 0,
      filtersRight: filters?.getBoundingClientRect().right ?? 0,
      filtersWidth: filters?.getBoundingClientRect().width ?? 0,
      primaryTops: ['.date-filter', '.rule-filter', '.assessment-filter', '.history-filter-reset'].map(top),
      secondaryTops: ['.operation-filter', '.amended-filter', '.stock-filter', '.reason-filter'].map(top),
    }
  })
  expect(geometry.panelWidth).toBeGreaterThan(0)
  expect(Math.abs(geometry.panelWidth - geometry.workspaceWidth)).toBeLessThanOrEqual(1)
  expect(geometry.filtersWidth).toBeLessThanOrEqual(1280)
  expect(Math.abs(
    (geometry.filtersLeft - geometry.filterCardLeft)
    - (geometry.filterCardRight - geometry.filtersRight),
  )).toBeLessThanOrEqual(1)
  expect(Math.max(...geometry.primaryTops) - Math.min(...geometry.primaryTops)).toBeLessThanOrEqual(1)
  expect(Math.max(...geometry.secondaryTops) - Math.min(...geometry.secondaryTops)).toBeLessThanOrEqual(1)
  expect(Math.min(...geometry.secondaryTops)).toBeGreaterThan(Math.max(...geometry.primaryTops))
}

test('真实夹具在三视口及超宽屏呈现生命周期全序、四类历史与稳定布局', async ({ page, request }, testInfo) => {
  const consoleIssues = collectConsoleIssues(page)
  const auth = await authenticateDebugUser(request, 'debug_normal')
  const fixture = await requireTradeDisciplineFixture(request, auth.accessToken, {
    verifyStockSearch: true,
  })
  await useAuth(page, auth)
  await page.goto(`/trade-discipline?tab=rules&rule_ref=${fixture.ruleId}`)

  const editor = page.getByTestId('rule-editor')
  await expect(editor).toContainText('当前正式 v4')
  await expect(editor.getByLabel('规则双状态')).toContainText('当前按 v3 履约')
  await expect(editor.getByLabel('规则双状态')).toContainText('发布 v4，待 2098-06-11 生效')

  await page.getByRole('button', { name: '历史记录', exact: true }).click()
  const history = page.getByRole('table', { name: '履约历史', exact: true })
  await expect(history).toBeVisible()
  for (const checkinId of fixture.checkinIds) {
    await expect(page.getByTestId(`history-detail-${checkinId}`)).toBeVisible()
  }
  await expect(history.getByText('已履约', { exact: true }).first()).toBeVisible()
  await expect(history.getByText('未履约', { exact: true }).first()).toBeVisible()
  await expect(history.getByText('无操作', { exact: true }).first()).toBeVisible()
  await expect(history.getByText('2 笔', { exact: true }).first()).toBeVisible()
  await expect(history.getByText('r2 · 已修正', { exact: true }).first()).toBeVisible()
  await expect(page.locator('.history-filter-card')).toBeVisible()
  await expectHistoryLayout(page)

  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    main: Math.max(...Array.from(document.querySelectorAll<HTMLElement>('[data-testid="app-main-surface"], .discipline-panel'))
      .map((element) => element.scrollWidth - element.clientWidth)),
  }))
  expect(overflow.document).toBeLessThanOrEqual(1)
  expect(overflow.main).toBeLessThanOrEqual(1)
  if (testInfo.project.name === 'chromium-default') {
    await page.setViewportSize({ width: 2560, height: 1080 })
    await expectHistoryLayout(page)
  }
  expect(consoleIssues).toEqual([])
})

test('标准视口真实完成规则、打卡、修订、快捷入口与权限闭环', async ({ page, request }, testInfo) => {
  test.setTimeout(120_000)
  test.skip(testInfo.project.name !== 'chromium-standard', '写链路只执行一次，其他项目只读验收')
  const consoleIssues = collectConsoleIssues(page, { allowedHttpStatuses: [500] })
  const normal = await authenticateDebugUser(request, 'debug_normal')
  const fixture = await requireTradeDisciplineFixture(request, normal.accessToken)
  await useAuth(page, normal)
  await page.goto('/stocks')
  await page.goto('/trade-discipline?tab=rules')

  await page.getByRole('button', { name: '新建规则' }).click()
  const editor = page.getByTestId('rule-editor')
  const e2eName = 'E2E纪律-T13页面全链路'
  await editor.getByTestId('rule-name-input').fill(e2eName)
  await editor.getByTestId('rule-capital-input').fill('100000.00')
  await editor.getByRole('button', { name: '添加选股规则' }).click()
  const stock = editor.getByTestId('stock-rule-card').first()
  await stock.getByTestId('stock-rule-name-input').fill('E2E趋势候选')
  await stock.getByTestId('stock-rule-capital-input').fill('100000.00')
  await stock.getByLabel('规则内容').fill('只选择确定性趋势候选')
  await editor.getByRole('button', { name: '添加买卖规则' }).click()
  await editor.getByRole('button', { name: '添加买卖规则' }).click()
  const actions = editor.getByTestId('action-rule-card')
  await actions.nth(0).getByTestId('action-rule-name-input').fill('E2E确认买入')
  await actions.nth(0).getByLabel('规则内容').fill('确认趋势后买入')
  await actions.nth(1).getByTestId('action-rule-name-input').fill('E2E破位卖出')
  await actions.nth(1).getByTestId('action-rule-side-select').getByRole('combobox').press('ArrowDown')
  await page.getByRole('option', { name: '卖出', exact: true }).click()
  await actions.nth(1).getByLabel('规则内容').fill('跌破关键位卖出')

  await page.getByRole('button', { name: '今日打卡', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '未保存的规则修改' })).toBeVisible()
  await chooseDialog(page, '继续编辑')
  await expect(editor.getByTestId('rule-name-input')).toHaveValue(e2eName)

  await page.route('**/api/trade-discipline/rules/*/draft', async (route) => {
    if (route.request().method() === 'PUT') {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ code: 5000, msg: 'E2E 注入保存失败', data: null }),
      })
    } else await route.continue()
  }, { times: 1 })
  await page.getByRole('button', { name: '今日打卡', exact: true }).click()
  await chooseDialog(page, '保存草稿')
  await expect(page.getByRole('dialog', { name: '未保存的规则修改' })).toBeVisible()
  await expect(editor.getByTestId('rule-name-input')).toHaveValue(e2eName)
  await chooseDialog(page, '保存草稿')
  await expect(page.getByRole('button', { name: '今日打卡', exact: true })).toHaveAttribute('aria-pressed', 'true')

  await page.getByRole('button', { name: '规则管理', exact: true }).click()
  await page.getByRole('option', { name: new RegExp(e2eName) }).click()
  await editor.getByRole('button', { name: '保存并启用' }).click()
  await expect(editor).toContainText('当前正式 v1')
  await editor.getByRole('button', { name: '归档', exact: true }).click()
  await chooseDialog(page, '归档')
  await expect(editor.getByLabel('规则双状态')).toContainText('归档已生效')
  await editor.getByRole('button', { name: '恢复', exact: true }).click()
  await chooseDialog(page, '恢复')
  await expect(editor.getByLabel('规则双状态')).toContainText('恢复已生效')

  await page.goto(`/trade-discipline?tab=checkin&rule_ref=${fixture.ruleId}&trade_date=${fixture.currentTradeDate}`)
  const checkin = page.getByTestId('checkin-form')
  await expect(checkin.getByTestId('checkin-version-kicker')).toHaveText('履约版本 v3')
  await checkin.getByTestId('checkin-assessment').getByText('未履约', { exact: true }).click()
  await checkin.getByTestId('checkin-no-operation').click()
  const reasonSelect = checkin.getByTestId('checkin-reason').getByRole('combobox')
  await reasonSelect.fill('E2E原因-T13临时偏差')
  await reasonSelect.press('Enter')
  await checkin.getByTestId('checkin-violation-detail').fill('E2E 页面真实提交')
  await checkin.getByTestId('checkin-review-note').fill('E2E 首次打卡现场')

  await page.getByRole('button', { name: '规则管理', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '放弃未提交修改？' })).toBeVisible()
  await chooseDialog(page, '继续编辑')
  await expect(checkin.getByTestId('checkin-review-note')).toHaveValue('E2E 首次打卡现场')
  await checkin.getByRole('button', { name: '提交打卡' }).click()
  await expect(checkin).toContainText('已提交 · r1')
  await checkin.getByRole('button', { name: '修正打卡' }).click()
  await reasonSelect.press('ArrowDown')
  await page.getByRole('option', { name: /E2E原因-T13临时偏差/ })
    .getByRole('button', { name: '删除自定义原因' }).click()
  await chooseDialog(page, '删除')
  await checkin.getByTestId('checkin-assessment').getByText('已履约', { exact: true }).click()
  await checkin.getByRole('button', { name: '提交修正' }).click()
  await expect(checkin).toContainText('已修正 · r2')

  await page.getByRole('button', { name: '历史记录', exact: true }).click()
  await expect(page.getByRole('table', { name: '履约历史', exact: true }).getByText('r2 · 已修正', { exact: true })).toHaveCount(2)
  const currentHistoryRow = page.getByRole('row').filter({ hasText: fixture.currentTradeDate })
  await expect(currentHistoryRow.getByRole('button', { name: '详情' })).toBeVisible()

  const submitOnly = await authenticateDebugUser(request, 'debug_trade_discipline_submit')
  await page.evaluate(() => localStorage.clear())
  await installAuthSnapshot(page, submitOnly)
  await page.goto('/stocks')
  await page.getByTestId('app-topbar-surface').getByRole('button', { name: '用户中心', exact: true }).click()
  const quickCard = page.getByTestId('trade-discipline-quick-card')
  await expect(quickCard).toContainText('0/1')
  await quickCard.getByRole('button', { name: '无操作履约' }).click()
  await chooseDialog(page, '确认打卡')
  await expect(quickCard).toContainText('1/1')

  const viewOnly = await authenticateDebugUser(request, 'debug_trade_discipline_view')
  await page.evaluate(() => localStorage.clear())
  await installAuthSnapshot(page, viewOnly)
  await page.goto(`/trade-discipline?tab=rules&rule_ref=e2e_td_trade_discipline_view_rule`)
  await expect(page.getByText('当前账号只有查看权限。')).toBeVisible()
  await expect(page.getByRole('button', { name: '新建规则' })).toHaveCount(0)
  await page.getByRole('button', { name: '今日打卡', exact: true }).click()
  await expect(page.getByText('当前账号仅可查看，不能提交或修正打卡。')).toBeVisible()
  await expect(page.getByRole('button', { name: '提交打卡' })).toHaveCount(0)

  const noPermission = await authenticateDebugUser(request, 'debug_board_only')
  await page.evaluate(() => localStorage.clear())
  await installAuthSnapshot(page, noPermission)
  await page.goto('/trade-discipline')
  await expect(page.getByRole('heading', { name: /每日榜单/ })).toBeVisible()
  await expect(page).not.toHaveURL(/\/trade-discipline/)
  expect(consoleIssues).toEqual([])
})

test('真实页面未保存协议拦截当前标签关闭、注销与浏览器刷新', async ({ page, request }, testInfo) => {
  test.setTimeout(60_000)
  test.skip(testInfo.project.name !== 'chromium-default', '未保存壳层链路只需在一个桌面视口执行')
  const auth = await authenticateDebugUser(request, 'debug_normal')
  await requireTradeDisciplineFixture(request, auth.accessToken)
  await useAuth(page, auth)
  await page.getByRole('menuitem', { name: '最新行情' }).click()
  await page.getByRole('menuitem', { name: '每日榜单' }).click()
  await expect(page).toHaveURL(/\/board$/)
  await page.getByRole('menuitem', { name: '交易纪律' }).click()
  await expect(page).toHaveURL(/\/trade-discipline/)
  await expect(page.getByRole('button', { name: '关闭 交易纪律' })).toBeVisible()
  await page.getByRole('button', { name: '规则管理', exact: true }).click()
  await page.getByRole('button', { name: '新建规则' }).click()
  await page.getByTestId('rule-name-input').fill('E2E纪律-T13未保存保护')
  const draftSaved = page.waitForResponse((response) => (
    response.request().method() === 'PUT'
      && /\/api\/trade-discipline\/rules\/[^/]+\/draft$/.test(new URL(response.url()).pathname)
      && response.ok()
  ))
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await draftSaved
  await page.getByTestId('rule-name-input').fill('E2E纪律-T13未保存保护-修改中')
  await expect(page.getByText('有未保存修改', { exact: true })).toBeVisible()

  const beforeUnloadPrevented = await page.evaluate(() => {
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    return event.defaultPrevented
  })
  expect(beforeUnloadPrevented).toBe(true)

  await page.getByRole('button', { name: '关闭 交易纪律' }).click()
  await expect(page.getByRole('dialog', { name: '未保存的规则修改' })).toBeVisible()
  await chooseDialog(page, '继续编辑')
  await expect(page).toHaveURL(/\/trade-discipline/)

  await page.getByTestId('app-topbar-surface').getByRole('button', { name: '用户中心', exact: true }).click()
  await page.getByRole('button', { name: '退出登录' }).click()
  await expect(page.getByRole('dialog', { name: '未保存的规则修改' })).toBeVisible()
  await chooseDialog(page, '继续编辑')
  await expect(page).toHaveURL(/\/trade-discipline/)
  await expect(page.getByTestId('rule-name-input')).toHaveValue('E2E纪律-T13未保存保护-修改中')
})
