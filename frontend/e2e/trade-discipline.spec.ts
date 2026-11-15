import { expect, test, type Locator, type Page } from '@playwright/test'

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

async function navigateToDailyBoard(page: Page): Promise<void> {
  await page.getByRole('menubar', { name: '侧栏导航' })
    .getByRole('menuitem', { name: '每日榜单', exact: true }).click()
}

async function navigateToSystemManagement(page: Page): Promise<void> {
  const topEntry = page.getByRole('button', { name: '系统管理', exact: true })
  if (await topEntry.isVisible()) {
    await topEntry.click()
    return
  }
  const permissionMenu = page.getByRole('menuitem', { name: '权限管理', exact: true })
  if (await permissionMenu.getAttribute('aria-expanded') !== 'true') await permissionMenu.click()
  await page.getByRole('menuitem', { name: '用户管理', exact: true }).click()
}

async function expectHistoryLayout(page: Page): Promise<void> {
  const geometry = await page.evaluate(() => {
    const panel = document.querySelector<HTMLElement>('.history-panel')
    const workspace = document.querySelector<HTMLElement>('.history-workspace')
    const filterCard = document.querySelector<HTMLElement>('.history-filter-card .el-card__body')
    const filters = document.querySelector<HTMLElement>('.history-filter-card .filter-row')
    const controlWidths = [
      '.date-filter', '.rule-filter', '.assessment-filter', '.operation-filter',
      '.amended-filter', '.stock-filter', '.reason-filter',
    ].map((selector) => document.querySelector<HTMLElement>(selector)?.getBoundingClientRect().width ?? 0)
    return {
      panelWidth: panel?.getBoundingClientRect().width ?? 0,
      workspaceWidth: workspace?.getBoundingClientRect().width ?? 0,
      filterCardLeft: filterCard?.getBoundingClientRect().left ?? 0,
      filterCardRight: filterCard?.getBoundingClientRect().right ?? 0,
      filtersLeft: filters?.getBoundingClientRect().left ?? 0,
      filtersRight: filters?.getBoundingClientRect().right ?? 0,
      filtersDisplay: filters ? getComputedStyle(filters).display : '',
      filterCardPaddingLeft: filterCard ? Number.parseFloat(getComputedStyle(filterCard).paddingLeft) : 0,
      filterCardPaddingRight: filterCard ? Number.parseFloat(getComputedStyle(filterCard).paddingRight) : 0,
      controlWidths,
    }
  })
  expect(geometry.panelWidth).toBeGreaterThan(0)
  expect(Math.abs(geometry.panelWidth - geometry.workspaceWidth)).toBeLessThanOrEqual(1)
  expect(geometry.filtersDisplay).toBe('flex')
  expect(Math.abs(
    geometry.filtersLeft - geometry.filterCardLeft - geometry.filterCardPaddingLeft,
  )).toBeLessThanOrEqual(1)
  expect(Math.abs(
    geometry.filterCardRight - geometry.filtersRight - geometry.filterCardPaddingRight,
  )).toBeLessThanOrEqual(1)
  expect(Math.min(...geometry.controlWidths)).toBeGreaterThan(0)
  expect(Math.max(...geometry.controlWidths)).toBeLessThanOrEqual(300)
}

async function expectPrimaryLeftAccent(
  locator: Locator,
  background: 'fill' | 'transparent' = 'transparent',
): Promise<void> {
  const styles = await locator.evaluate((element) => {
    const style = getComputedStyle(element)
    const primaryProbe = document.createElement('span')
    primaryProbe.style.color = 'var(--el-color-primary)'
    primaryProbe.style.backgroundColor = 'var(--el-fill-color-extra-light)'
    element.append(primaryProbe)
    const fillBackgroundColor = getComputedStyle(primaryProbe).backgroundColor
    const primaryColor = getComputedStyle(primaryProbe).color
    primaryProbe.remove()
    return {
      backgroundColor: style.backgroundColor,
      borderBottomWidth: style.borderBottomWidth,
      borderLeftColor: style.borderLeftColor,
      borderLeftStyle: style.borderLeftStyle,
      borderLeftWidth: style.borderLeftWidth,
      borderRightWidth: style.borderRightWidth,
      borderTopWidth: style.borderTopWidth,
      color: style.color,
      fillBackgroundColor,
      primaryColor,
    }
  })
  expect(styles).toMatchObject({
    backgroundColor: background === 'fill'
      ? styles.fillBackgroundColor
      : 'rgba(0, 0, 0, 0)',
    borderBottomWidth: '0px',
    borderLeftColor: styles.primaryColor,
    borderLeftStyle: 'solid',
    borderLeftWidth: '3px',
    borderRightWidth: '0px',
    borderTopWidth: '0px',
  })
  expect(styles.color).not.toBe(styles.primaryColor)
}

async function expectWorkspaceSurface(locator: Locator): Promise<void> {
  const colors = await locator.evaluate((element) => {
    const probe = document.createElement('span')
    probe.style.backgroundColor = 'var(--el-bg-color)'
    element.append(probe)
    const surfaceColor = getComputedStyle(probe).backgroundColor
    probe.remove()
    return {
      backgroundColor: getComputedStyle(element).backgroundColor,
      surfaceColor,
    }
  })
  expect(colors.backgroundColor).toBe(colors.surfaceColor)
}

async function expectChildFillsContainer(container: Locator, childSelector: string): Promise<void> {
  const geometry = await container.evaluate((element, selector) => {
    const child = element.querySelector<HTMLElement>(selector)
    const style = getComputedStyle(element)
    const contentWidth = element.clientWidth
      - Number.parseFloat(style.paddingLeft)
      - Number.parseFloat(style.paddingRight)
    return {
      childWidth: child?.getBoundingClientRect().width ?? 0,
      contentWidth,
    }
  }, childSelector)
  expect(geometry.childWidth).toBeGreaterThan(0)
  expect(Math.abs(geometry.contentWidth - geometry.childWidth)).toBeLessThanOrEqual(1)
}

async function expectOperationEditorLayout(checkin: Locator): Promise<void> {
  const geometry = await checkin.getByTestId('operation-card-editor').evaluate((editor) => {
    const grid = editor.querySelector<HTMLElement>('.operation-grid')
    const stock = editor.querySelector<HTMLElement>('.operation-field--stock')
    const time = editor.querySelector<HTMLElement>('.operation-field--time')
    const rules = Array.from(editor.querySelectorAll<HTMLElement>('.operation-field--rule'))
    const amounts = Array.from(editor.querySelectorAll<HTMLElement>('.operation-field--amount'))
    return {
      gridWidth: grid?.getBoundingClientRect().width ?? 0,
      stockWidth: stock?.getBoundingClientRect().width ?? 0,
      timeWidth: time?.getBoundingClientRect().width ?? 0,
      ruleWidths: rules.map((item) => item.getBoundingClientRect().width),
      amountWidths: amounts.map((item) => item.getBoundingClientRect().width),
    }
  })
  expect(geometry.gridWidth).toBeGreaterThan(0)
  expect(geometry.stockWidth).toBeGreaterThan(0)
  expect(geometry.timeWidth).toBeGreaterThan(0)
  expect(Math.abs(geometry.stockWidth - geometry.timeWidth)).toBeLessThanOrEqual(1)
  expect(geometry.ruleWidths).toHaveLength(2)
  expect(Math.abs(geometry.ruleWidths[0]! - geometry.ruleWidths[1]!)).toBeLessThanOrEqual(1)
  expect(geometry.amountWidths).toHaveLength(4)
  expect(Math.max(...geometry.amountWidths) - Math.min(...geometry.amountWidths)).toBeLessThanOrEqual(1)
}

test('真实夹具在三视口及超宽屏呈现生命周期全序、四类历史与稳定布局', async ({ page, request }, testInfo) => {
  const consoleIssues = collectConsoleIssues(page)
  const auth = await authenticateDebugUser(request, 'debug_normal')
  const fixture = await requireTradeDisciplineFixture(request, auth.accessToken, {
    verifyStockSearch: true,
  })
  await useAuth(page, auth)
  const initialViewport = page.viewportSize()
  if (testInfo.project.name === 'chromium-default') {
    await page.setViewportSize({ width: 2560, height: 1080 })
  }
  await page.goto(`/trade-discipline?tab=rules&rule_ref=${fixture.ruleId}`)

  const editor = page.getByTestId('rule-editor')
  await expect(editor).toContainText('当前正式 v4')
  await expect(editor.getByLabel('规则双状态')).toContainText('当前按 v3 履约')
  await expect(editor.getByLabel('规则双状态')).toContainText('发布 v4，待 2098-06-11 生效')
  await expectWorkspaceSurface(editor)
  await expectPrimaryLeftAccent(editor.locator('.readonly-banner'))
  await expect(editor.getByTestId('rule-capital-input')).toBeDisabled()
  await editor.getByTestId('stock-rule-card').first().getByTestId('rule-card-toggle').click()
  await expect(editor.getByTestId('stock-rule-capital-input').first()).toBeDisabled()
  await expectWorkspaceSurface(editor.getByTestId('rule-card-editor'))
  await editor.getByTestId('buy-rule-group').getByTestId('rule-card-toggle').first().click()
  const typeHelp = editor.getByTestId('action-rule-type-help')
  await typeHelp.hover()
  await expect(page.getByText('内置类型不可删除；输入新类型并保存后可复用，自定义类型可从下拉项删除。', { exact: true })).toBeVisible()
  await expectChildFillsContainer(editor, '.rule-editor__form')

  await page.goto(`/trade-discipline?tab=checkin&rule_ref=${fixture.ruleId}&trade_date=${TRADE_DISCIPLINE_FIXTURE.operationTradeDate}`)
  const checkin = page.getByTestId('checkin-form')
  const operationCards = checkin.getByTestId('operation-card')
  await expect(operationCards).toHaveCount(2)
  await expect(checkin.getByTestId('buy-operation-group')).toContainText('买入操作')
  await expect(checkin.getByTestId('sell-operation-group')).toContainText('卖出操作')
  await expect(checkin.getByTestId('buy-operation-group').getByTestId('operation-card')).toHaveCount(1)
  await expect(checkin.getByTestId('sell-operation-group').getByTestId('operation-card')).toHaveCount(1)
  await expect(checkin.getByTestId('operation-card-editor')).toHaveCount(0)
  await expect(operationCards.first()).toContainText('E2E股票01 998801.SZ')
  await expect(operationCards.first()).toContainText('成交金额 · 12,345.60')
  const operationToggles = checkin.getByTestId('operation-card-toggle')
  await operationToggles.first().click()
  await expect(checkin.getByTestId('operation-card-editor')).toHaveCount(1)
  await expect(operationToggles.first()).toHaveAttribute('aria-expanded', 'true')
  await expect(checkin.getByTestId('operation-card-editor').getByText('方向', { exact: true })).toHaveCount(0)
  await expect(checkin.getByTestId('operation-card-editor').getByText('买入规则', { exact: true })).toBeVisible()
  await operationToggles.nth(1).click()
  await expect(checkin.getByTestId('operation-card-editor')).toHaveCount(1)
  await expect(operationToggles.first()).toHaveAttribute('aria-expanded', 'false')
  await expect(operationToggles.nth(1)).toHaveAttribute('aria-expanded', 'true')
  await expect(checkin.getByTestId('operation-card-editor').getByText('卖出规则', { exact: true })).toBeVisible()
  await expectWorkspaceSurface(page.locator('.panel-detail'))
  await expectWorkspaceSurface(checkin.getByTestId('operation-card-editor'))
  await expectChildFillsContainer(checkin, '.checkin-form')
  await expectChildFillsContainer(checkin.getByTestId('operation-card-editor'), '.operation-grid')
  await expectOperationEditorLayout(checkin)

  await checkin.getByRole('button', { name: '修正打卡', exact: true }).click()
  await checkin.getByTestId('checkin-assessment').getByText('部分履约', { exact: true }).click()
  await expect(checkin.getByTestId('checkin-no-operation')).toBeDisabled()
  await expect(operationCards.first()).toContainText('已履约')
  await expect(operationCards.nth(1)).toContainText('已履约')
  await operationToggles.first().click()
  await checkin.getByTestId('operation-compliance-0').getByText('已履约', { exact: true }).click()
  await operationToggles.nth(1).click()
  await checkin.getByTestId('operation-compliance-1').getByText('未履约', { exact: true }).click()
  await expect(operationCards.first()).toContainText('已履约')
  await expect(operationCards.nth(1)).toContainText('未履约')
  await checkin.getByRole('button', { name: '取消修正', exact: true }).click()

  if (testInfo.project.name === 'chromium-default' && initialViewport) {
    await page.setViewportSize(initialViewport)
  }

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

  const startDate = page.getByPlaceholder('开始交易日')
  await startDate.click()
  const calendar = page.locator('.trade-cal:visible')
  await expect(calendar).toBeVisible()
  const calendarGeometry = await page.evaluate(() => {
    const input = document.querySelector<HTMLElement>('input[placeholder="开始交易日"]')
    const panel = Array.from(document.querySelectorAll<HTMLElement>('.trade-cal'))
      .find((element) => getComputedStyle(element).display !== 'none')
    return {
      inputBottom: input?.getBoundingClientRect().bottom ?? 0,
      panelTop: panel?.getBoundingClientRect().top ?? 0,
    }
  })
  expect(calendarGeometry.panelTop).toBeGreaterThanOrEqual(calendarGeometry.inputBottom - 1)
  await page.keyboard.press('Escape')

  const firstMainRow = page.locator('.history-workspace .el-table__body-wrapper tbody tr').first()
  const latestDateBeforeSort = (await firstMainRow.locator('td').first().innerText()).trim()
  const ascResponse = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return url.pathname === '/api/trade-discipline/checkins'
      && url.searchParams.get('sort_order') === 'asc'
      && response.ok()
  })
  await page.getByRole('button', { name: '按 交易日 排序' }).press('Enter')
  await ascResponse
  await expect(firstMainRow).toContainText('2098-06-04')

  const descResponse = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return url.pathname === '/api/trade-discipline/checkins'
      && url.searchParams.get('sort_order') === 'desc'
      && response.ok()
  })
  await page.getByRole('button', { name: '按 交易日 排序' }).press('Enter')
  await descResponse
  await expect(firstMainRow.locator('td').first()).toHaveText(latestDateBeforeSort)

  await page.getByTestId('page-settings-trigger').click()
  const settingsDrawer = page.getByTestId('page-settings-drawer')
  await expect(settingsDrawer.getByText('列显隐', { exact: true })).toBeVisible()
  for (const column of [
    'trade_date', 'rule_name', 'assessment', 'operation_count',
    'reason_name_snapshot', 'current_revision_no', 'updated_at',
  ]) {
    await expect(settingsDrawer.getByTestId(
      `component-history-hiddenColumns-${column}-switch`,
    )).toBeVisible()
  }
  await settingsDrawer.getByRole('button', { name: '关闭页面设置' }).click()

  await expect(page.locator('.trade-date-summary')).toHaveCount(0)
  await expect(page.locator('.discipline-summary')).toHaveCount(0)

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

test('从缓存的交易纪律历史切换系统管理不触发隐藏页面请求', async ({ page, request }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-standard', '跨模块导航链路只需在一个桌面视口执行')
  const consoleIssues = collectConsoleIssues(page)
  const auth = await authenticateDebugUser(request, 'debug_tenant_admin')
  await requireTradeDisciplineFixture(request, auth.accessToken)
  await useAuth(page, auth)
  await page.goto('/trade-discipline?tab=history&trade_date=2098-06-10')
  await expect(page.getByRole('table', { name: '履约历史', exact: true })).toBeVisible()

  const hiddenPageRequests: string[] = []
  page.on('request', (request) => {
    const pathname = new URL(request.url()).pathname
    if (pathname.startsWith('/api/trade-discipline/')) hiddenPageRequests.push(pathname)
  })
  await navigateToSystemManagement(page)
  await expect(page).toHaveURL(/\/system\//)
  await page.waitForTimeout(300)

  expect(hiddenPageRequests).toEqual([])
  await expect(page.getByText('履约日期不是已有行情交易日', { exact: true })).toHaveCount(0)
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
  await stock.locator('[data-condition-section="notes"] [role="button"]').click()
  await stock.getByLabel('补充说明', { exact: true }).fill('只选择确定性趋势候选')
  const buyGroup = editor.getByTestId('buy-rule-group')
  const sellGroup = editor.getByTestId('sell-rule-group')
  await buyGroup.getByRole('button', { name: '添加', exact: true }).click()
  const buyRule = buyGroup.getByTestId('action-rule-card').first()
  await buyRule.getByTestId('action-rule-name-input').fill('E2E确认买入')
  const buyType = buyRule.getByTestId('action-rule-type-select').getByRole('combobox')
  await buyType.click()
  await page.getByRole('option', { name: '建仓', exact: true }).click()
  await buyRule.getByLabel('规则内容').fill('确认趋势后买入')
  await buyRule.getByRole('button', { name: '复制买卖规则' }).click()
  await expect(buyGroup.getByTestId('action-rule-card')).toHaveCount(2)

  await sellGroup.getByRole('button', { name: '添加', exact: true }).click()
  const sellRule = sellGroup.getByTestId('action-rule-card').first()
  await sellRule.getByTestId('action-rule-name-input').fill('E2E破位卖出')
  await sellRule.getByLabel('规则内容').fill('跌破关键位卖出')

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
  await expect(editor.getByTestId('rule-card-editor')).toHaveCount(0)
  await editor.getByTestId('stock-rule-card').first().getByTestId('rule-card-toggle').click()
  await expect(editor.getByTestId('rule-card-editor')).toHaveCount(1)
  await editor.getByTestId('buy-rule-group').getByTestId('rule-card-toggle').first().click()
  await expect(editor.getByTestId('rule-card-editor')).toHaveCount(1)
  const savedBuyType = editor.getByTestId('buy-rule-group')
    .getByTestId('action-rule-card').first()
    .getByTestId('action-rule-type-select').getByRole('combobox')
  await savedBuyType.press('ArrowDown')
  await expect(page.getByRole('option', { name: '建仓', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '删除自定义买卖类型' })).toHaveCount(0)
  await savedBuyType.press('Escape')
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
  await checkin.getByTestId('checkin-violation-items').getByRole('checkbox', { name: '应卖未卖', exact: true }).check()
  const reasonSelect = checkin.getByTestId('checkin-reason').getByRole('combobox')
  await reasonSelect.fill('E2E原因-T13临时偏差')
  await page.getByRole('option', { name: 'E2E原因-T13临时偏差', exact: true }).click()
  await expect(checkin.getByTestId('checkin-reason')).toContainText('E2E原因-T13临时偏差')
  await checkin.getByTestId('checkin-violation-detail').fill('E2E 页面真实提交')
  await checkin.getByTestId('checkin-review-note').fill('E2E 首次打卡现场')

  await page.getByRole('button', { name: '规则管理', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '放弃未提交修改？' })).toBeVisible()
  await chooseDialog(page, '继续编辑')
  await expect(checkin.getByTestId('checkin-review-note')).toHaveValue('E2E 首次打卡现场')
  await expect(checkin.getByTestId('checkin-reason')).toContainText('E2E原因-T13临时偏差')
  await checkin.getByRole('button', { name: '提交打卡' }).click()
  await expect(page.locator('.rule-master__item.active .rule-master__management'))
    .toContainText('未履约 · r1')
  await checkin.getByRole('button', { name: '修正打卡' }).click()
  await expect(checkin.getByRole('button', { name: '提交修正' })).toBeDisabled()
  await expect(checkin).toContainText('当前内容与最新修订一致；修改后才可提交')
  await checkin.getByTestId('checkin-review-note').fill('应被取消的修正')
  await checkin.getByRole('button', { name: '取消修正' }).click()
  await expect(checkin.getByTestId('checkin-review-note')).toHaveValue('E2E 首次打卡现场')
  await expect(checkin.getByTestId('checkin-review-note')).toBeDisabled()
  await checkin.getByRole('button', { name: '修正打卡' }).click()
  await reasonSelect.press('ArrowDown')
  await page.getByRole('option', { name: /E2E原因-T13临时偏差/ })
    .getByRole('button', { name: '删除自定义原因' }).click()
  await chooseDialog(page, '删除')
  await checkin.getByTestId('checkin-assessment').getByText('已履约', { exact: true }).click()
  await checkin.getByRole('button', { name: '提交修正' }).click()
  await expect(page.locator('.rule-master__item.active .rule-master__management'))
    .toContainText('已履约 · r2')

  await page.getByRole('button', { name: '历史记录', exact: true }).click()
  await expect(page.getByRole('table', { name: '履约历史', exact: true }).getByText('r2 · 已修正', { exact: true })).toHaveCount(2)
  const currentHistoryRow = page.getByRole('row').filter({ hasText: fixture.currentTradeDate })
  await expect(currentHistoryRow.getByRole('button', { name: /^查看.+详情$/ })).toBeVisible()

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
  await expectPrimaryLeftAccent(page.locator('.readonly-banner'))
  await expect(page.getByRole('button', { name: '新建规则' })).toHaveCount(0)
  await page.getByRole('button', { name: '今日打卡', exact: true }).click()
  await expect(page.getByText('当前账号仅可查看，不能提交或修正打卡。')).toBeVisible()
  await expectPrimaryLeftAccent(page.locator('.permission-note'))
  await expect(page.getByRole('button', { name: '提交打卡' })).toHaveCount(0)
  await page.getByRole('button', { name: '历史记录', exact: true }).click()
  const readonlyStockSearch = page.waitForResponse((response) => (
    new URL(response.url()).pathname === '/api/trade-discipline/stock-options'
      && response.status() === 200
  ))
  await page.locator('.stock-filter').getByRole('combobox').fill('998803')
  await readonlyStockSearch
  await expect(page.getByRole('option', { name: /998803\.SZ.*E2E股票03/ })).toContainText('已退市')

  const noPermission = await authenticateDebugUser(request, 'debug_board_only')
  await page.evaluate(() => localStorage.clear())
  await installAuthSnapshot(page, noPermission)
  await page.goto('/trade-discipline')
  await expect(page.getByRole('heading', { name: /每日榜单/ })).toBeVisible()
  await expect(page).not.toHaveURL(/\/trade-discipline/)
  expect(consoleIssues).toEqual([])
})

test('真实页面未保存协议拦截路由、当前标签关闭、注销与浏览器刷新', async ({ page, request }, testInfo) => {
  test.setTimeout(60_000)
  test.skip(testInfo.project.name !== 'chromium-default', '未保存壳层链路只需在一个桌面视口执行')
  const auth = await authenticateDebugUser(request, 'debug_normal')
  await requireTradeDisciplineFixture(request, auth.accessToken)
  await useAuth(page, auth)
  await navigateToDailyBoard(page)
  await expect(page).toHaveURL(/\/board$/)
  await page.getByRole('tab', { name: '交易纪律' }).click()
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
  await page.getByRole('button', { name: '重置', exact: true }).click()
  await expect(page.getByTestId('rule-name-input')).toHaveValue('E2E纪律-T13未保存保护')
  await expect(page.getByText('有未保存修改', { exact: true })).toHaveCount(0)
  await page.getByTestId('rule-name-input').fill('E2E纪律-T13未保存保护-修改中')
  await expect(page.getByText('有未保存修改', { exact: true })).toBeVisible()

  await navigateToDailyBoard(page)
  await expect(page.getByRole('dialog', { name: '未保存的规则修改' })).toBeVisible()
  await chooseDialog(page, '继续编辑')
  await expect(page).toHaveURL(/\/trade-discipline/)
  await expect(page.getByTestId('rule-name-input'))
    .toHaveValue('E2E纪律-T13未保存保护-修改中')

  const nativeDialog = page.waitForEvent('dialog')
  const reloadAttempt = page.reload({ waitUntil: 'domcontentloaded', timeout: 10_000 })
    .catch(() => null)
  const dialog = await nativeDialog
  expect(dialog.type()).toBe('beforeunload')
  await dialog.dismiss()
  await reloadAttempt
  await expect(page).toHaveURL(/\/trade-discipline/)
  await expect(page.getByTestId('rule-name-input'))
    .toHaveValue('E2E纪律-T13未保存保护-修改中')

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
