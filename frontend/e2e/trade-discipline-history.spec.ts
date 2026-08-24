import { expect, test } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'

test('交易纪律历史可筛选、切换不可变修订并完成修正返回', async ({ page, request }) => {
  const consoleIssues = collectConsoleIssues(page)
  let currentRevision = 2
  const historyQueries: string[] = []
  const tradeDate = '2026-08-22'
  const ruleVersion = {
    rule_id: 'e2e-rule-1', version_no: 3, name: 'E2E 趋势纪律', capital: '100000',
    stock_rules: [{ detail_id: 'sr-1', name: '龙头', max_capital: '50000', content: '只做趋势龙头', display_order: 1, enabled: true }],
    action_rules: [{ detail_id: 'ar-1', name: '突破买入', action_type: 'buy', action_subtype: 'open_position', content: '放量突破后执行', display_order: 1, enabled: true }],
  }
  const checkin = () => ({
    checkin_id: 'e2e-checkin-1', revision_no: currentRevision, current_revision_no: currentRevision,
    rule_id: 'e2e-rule-1', rule_name: 'E2E 趋势纪律', version_no: 3, trade_date: tradeDate,
    checkin_status: currentRevision > 1 ? 'amended' : 'submitted', assessment: 'breached',
    no_operation: true, reason_code: 'impulsive', reason_id: null,
    reason_name_snapshot: '冲动交易', violation_detail: '偏离既定计划', review_note: '盘后复核',
    operations: [], financial_complete: true, created_at: `${tradeDate}T19:00:00`,
  })
  const historyRow = () => ({
    id: 'e2e-checkin-1', rule_id: 'e2e-rule-1', rule_name: 'E2E 趋势纪律', trade_date: tradeDate,
    status: currentRevision > 1 ? 'amended' : 'submitted', current_revision_no: currentRevision,
    version_no: 3, assessment: 'breached', no_operation: true, reason_name_snapshot: '冲动交易',
    operation_count: 0, submitted_at: `${tradeDate}T18:00:00`, amended_at: `${tradeDate}T19:00:00`,
    updated_at: `${tradeDate}T19:00:00`,
  })
  const apiResponse = (data: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 0, msg: 'ok', data }) })

  await page.route('**/api/trade-discipline/**', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname
    if (path.endsWith('/rules') && req.method() === 'GET') {
      await route.fulfill(apiResponse([{
        id: 'e2e-rule-1', name: 'E2E 趋势纪律', status: 'active', latest_version_no: 3,
        management_status: 'active', latest_management_event: null, has_pending_management_action: false,
        effective_status: 'active', effective_event_seq: 1, effective_from_trade_date: tradeDate,
        effective_version: { version_no: 3, name: 'E2E 趋势纪律', capital: '100000' },
      }]))
      return
    }
    if (path.endsWith('/summary')) {
      await route.fulfill(apiResponse({
        trade_date: url.searchParams.get('trade_date') || tradeDate, total: 1, completed: 1, pending: 0,
        rules: [{ rule_id: 'e2e-rule-1', rule_name: 'E2E 趋势纪律', version_no: 3, effective_from_trade_date: tradeDate, checkin_id: 'e2e-checkin-1', current_revision_no: currentRevision, status: 'amended', assessment: 'breached', no_operation: true }],
      }))
      return
    }
    if (path.endsWith('/checkins/current')) {
      await route.fulfill(apiResponse({ trade_date: tradeDate, version: ruleVersion, checkin: checkin() }))
      return
    }
    if (/\/checkins\/e2e-checkin-1\/revisions\/\d+$/.test(path)) {
      const revisionNo = Number(path.split('/').at(-1))
      await route.fulfill(apiResponse({ ...checkin(), revision_no: revisionNo, rule_version: ruleVersion }))
      return
    }
    if (path.endsWith('/checkins/e2e-checkin-1/amendments') && req.method() === 'POST') {
      currentRevision += 1
      await route.fulfill(apiResponse(checkin()))
      return
    }
    if (path.endsWith('/checkins') && req.method() === 'GET') {
      historyQueries.push(url.search)
      await route.fulfill(apiResponse({ total: 1, page: 1, page_size: 20, list: [historyRow()] }))
      return
    }
    await route.continue()
  })

  await loginAsDebugUser(page, request, 'debug_normal')
  await page.goto('/trade-discipline?tab=history')
  await expect(page.getByText('E2E 趋势纪律 · v3')).toBeVisible()

  await page.getByTestId('history-assessment-filter').getByRole('combobox').press('ArrowDown')
  await page.getByRole('option', { name: '未履约' }).click()
  await expect.poll(() => historyQueries.some((query) => query.includes('assessment=breached'))).toBe(true)
  await expect(page.getByText('冲动交易').first()).toBeVisible()

  await page.getByTestId('history-detail-e2e-checkin-1').press('Enter')
  const drawer = page.getByTestId('checkin-revision-drawer')
  await expect(drawer).toContainText('规则版本快照')
  await expect(drawer).toContainText('只做趋势龙头')

  await drawer.getByTestId('revision-selector').getByRole('combobox').press('ArrowDown')
  await page.getByRole('option', { name: 'r1' }).click()
  await expect(drawer).toContainText('历史修订 · 只读')
  await expect(drawer.getByRole('button', { name: '发起修正' })).toBeDisabled()

  await drawer.getByTestId('revision-selector').getByRole('combobox').press('ArrowDown')
  await page.getByRole('option', { name: 'r2 · 当前' }).click()
  await drawer.getByRole('button', { name: '发起修正' }).click()
  const amendButton = page.getByRole('button', { name: '提交修正' })
  await expect(amendButton).toBeDisabled()
  await page.getByTestId('checkin-review-note').fill('盘后复核（修正）')
  await expect(amendButton).toBeEnabled()
  await amendButton.click()

  await expect(page).toHaveURL(/tab=history/)
  await expect(page.getByText('r3 · 已修正')).toBeVisible()
  await expect(page.getByTestId('history-assessment-filter')).toContainText('未履约')
  expect(historyQueries.at(-1)).toContain('assessment=breached')
  expect(consoleIssues).toEqual([])
})
