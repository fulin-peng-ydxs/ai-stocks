import { expect, test } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'

test('任意授权业务页可发现待打卡状态并完成快捷无操作履约', async ({ page, request }) => {
  const consoleIssues = collectConsoleIssues(page)
  let firstCompleted = false
  let submittedPayload: Record<string, unknown> | null = null
  const apiResponse = (data: unknown) => ({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ code: 0, msg: 'ok', data }),
  })

  await page.route('**/api/trade-discipline/**', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const tradeDate = url.searchParams.get('trade_date') || '2026-08-22'
    if (url.pathname.endsWith('/summary')) {
      await route.fulfill(apiResponse({
        trade_date: tradeDate,
        total: 2,
        completed: firstCompleted ? 1 : 0,
        pending: firstCompleted ? 1 : 2,
        rules: [
          {
            rule_id: 'quick-rule-1', rule_name: '趋势纪律', version_no: 2,
            effective_from_trade_date: tradeDate,
            checkin_id: firstCompleted ? 'quick-checkin-1' : null,
            current_revision_no: firstCompleted ? 1 : null,
            status: firstCompleted ? 'submitted' : null,
            assessment: firstCompleted ? 'complied' : null,
            no_operation: firstCompleted ? true : null,
          },
          {
            rule_id: 'quick-rule-2', rule_name: '防守纪律', version_no: 1,
            effective_from_trade_date: tradeDate, checkin_id: null,
            current_revision_no: null, status: null, assessment: null, no_operation: null,
          },
        ],
      }))
      return
    }
    if (url.pathname.endsWith('/checkins/quick-no-operation') && req.method() === 'POST') {
      submittedPayload = req.postDataJSON() as Record<string, unknown>
      firstCompleted = true
      await route.fulfill(apiResponse({
        checkin_id: 'quick-checkin-1', rule_id: 'quick-rule-1', trade_date: submittedPayload.trade_date,
        idempotent: false,
      }))
      return
    }
    if (url.pathname.endsWith('/rules') && req.method() === 'GET') {
      await route.fulfill(apiResponse([
        {
          id: 'quick-rule-1', name: '趋势纪律', status: 'active', latest_version_no: 2,
          management_status: 'active', latest_management_event: null,
          has_pending_management_action: false, effective_status: 'active', effective_event_seq: 2,
          effective_from_trade_date: tradeDate,
          effective_version: { version_no: 2, name: '趋势纪律', capital: '100000' },
        },
        {
          id: 'quick-rule-2', name: '防守纪律', status: 'active', latest_version_no: 1,
          management_status: 'active', latest_management_event: null,
          has_pending_management_action: false, effective_status: 'active', effective_event_seq: 1,
          effective_from_trade_date: tradeDate,
          effective_version: { version_no: 1, name: '防守纪律', capital: '80000' },
        },
      ]))
      return
    }
    if (/\/rules\/quick-rule-\d+$/.test(url.pathname) && req.method() === 'GET') {
      const ruleId = url.pathname.split('/').at(-1)!
      const isTrend = ruleId === 'quick-rule-1'
      const versionNo = isTrend ? 2 : 1
      const name = isTrend ? '趋势纪律' : '防守纪律'
      const version = {
        rule_id: ruleId, version_no: versionNo, name, capital: isTrend ? '100000' : '80000',
        stock_rules: [], action_rules: [],
      }
      await route.fulfill(apiResponse({
        id: ruleId, name, status: 'active', latest_version_no: versionNo,
        draft_revision: null, proposed_name: name, management_status: 'active',
        latest_management_event: null, has_pending_management_action: false,
        effective_status: 'active', effective_event_seq: versionNo,
        effective_from_trade_date: tradeDate, effective_version: version,
        latest_version: version, draft: null,
      }))
      return
    }
    if (url.pathname.endsWith('/checkins/current')) {
      await route.fulfill(apiResponse({
        trade_date: tradeDate,
        version: {
          rule_id: 'quick-rule-2', version_no: 1, name: '防守纪律', capital: '80000',
          stock_rules: [{
            detail_id: 'stock-rule-1', name: '防守选股', max_capital: '80000',
            content: '只做低风险机会', display_order: 1, enabled: true,
          }],
          action_rules: [
            { detail_id: 'action-buy-1', name: '确认买入', action_type: 'buy', action_subtype: 'open_position', content: '确认后买入', display_order: 1, enabled: true },
            { detail_id: 'action-sell-1', name: '风险卖出', action_type: 'sell', action_subtype: 'liquidate', content: '触发风险即卖出', display_order: 2, enabled: true },
          ],
        },
        checkin: null,
      }))
      return
    }
    await route.continue()
  })

  await loginAsDebugUser(page, request, 'debug_normal')
  await page.goto('/stocks')

  await expect(page.getByLabel('有待打卡交易纪律')).toBeVisible()
  await page.getByTestId('app-topbar-surface').getByRole('button', { name: '用户中心', exact: true }).click()
  const card = page.getByTestId('trade-discipline-quick-card')
  await expect(card).toContainText('已完成')
  await expect(card).toContainText('0/2')

  const trendRow = card.locator('article').filter({ hasText: '趋势纪律' })
  await trendRow.getByRole('button', { name: '无操作履约' }).click()
  await page.getByRole('button', { name: '确认打卡' }).click()
  await expect(trendRow).toContainText('已履约')
  expect(submittedPayload).toEqual({
    rule_id: 'quick-rule-1',
    trade_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
  })

  const defensiveRow = card.locator('article').filter({ hasText: '防守纪律' })
  await defensiveRow.getByRole('button', { name: '去打卡' }).click()
  await expect(page).toHaveURL(/\/trade-discipline\?tab=checkin&rule_ref=quick-rule-2&trade_date=/)
  await expect(page.getByRole('heading', { name: '防守纪律' })).toBeVisible()
  await expect(page.getByTestId('checkin-version-kicker')).toHaveText('履约版本 v1')

  await page.getByTestId('app-topbar-surface').getByRole('button', { name: '用户中心', exact: true }).click()
  await page.getByTestId('trade-discipline-quick-card').getByRole('button', { name: '管理规则' }).click()
  await expect(page).toHaveURL(/\/trade-discipline\?tab=rules/)
  await expect(page.getByRole('button', { name: '规则管理' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('listbox', { name: '选择交易规则' })).toBeVisible()
  expect(consoleIssues).toEqual([])
})
