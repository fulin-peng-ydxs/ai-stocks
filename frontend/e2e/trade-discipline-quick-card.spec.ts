import { expect, test } from '@playwright/test'
import type { RuleVersionDetail } from '../src/api/tradeDiscipline'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { installLedgerUiCalendar, makeLedgerContext, makeLedgerSnapshot } from './helpers/tradeDiscipline'

test.use({ actionTimeout: 15_000 })

test('业务页快捷确认只完成指定规则，待打卡与空态导航接入当前账户', async ({ page, request }) => {
  const issues = collectConsoleIssues(page)
  const tradeDate = '2026-08-21'
  await installLedgerUiCalendar(page, tradeDate)
  let completed = false
  let empty = false
  const submitted: unknown[] = []
  const versions: RuleVersionDetail[] = ['趋势纪律', '防守纪律'].map((name, i) => ({
    rule_id: `quick-rule-${i + 1}`, version_no: i === 0 ? 2 : 1, name, capital: '100000',
    stock_rules: [], action_rules: [],
  }))
  const respond = (data: unknown) => ({ contentType: 'application/json', body: JSON.stringify({ code: 0, msg: 'ok', data }) })
  await page.route('**/api/trade-discipline/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname
    if (path.endsWith('/summary')) return route.fulfill(respond({ trade_date: tradeDate,
      total: empty ? 0 : 2, completed: empty ? 0 : completed ? 1 : 0, pending: empty ? 0 : completed ? 1 : 2,
      rules: empty ? [] : versions.map((rule, i) => ({ rule_id: rule.rule_id, rule_name: rule.name,
        version_no: rule.version_no, effective_from_trade_date: tradeDate,
        checkin_id: completed && i === 0 ? 'quick-ledger-day' : null,
        current_revision_no: completed && i === 0 ? 1 : null,
        status: completed && i === 0 ? 'submitted' : null,
        assessment: completed && i === 0 ? 'complied' : null, no_operation: completed && i === 0 ? true : null,
      })) }))
    if (path.endsWith('/checkins/quick-no-operation') && req.method() === 'POST') {
      submitted.push(req.postDataJSON())
      completed = true
      return route.fulfill(respond({ checkin_id: 'quick-ledger-day', trade_date: tradeDate, idempotent: false }))
    }
    const rules = (empty ? [] : versions).map(rule => ({ id: rule.rule_id, name: rule.name, status: 'active',
      latest_version_no: rule.version_no, management_status: 'active', latest_management_event: null,
      has_pending_management_action: false, effective_status: 'active', effective_event_seq: 1,
      effective_from_trade_date: tradeDate, effective_version: rule,
    }))
    if (path.endsWith('/rules') && req.method() === 'GET') return route.fulfill(respond(rules))
    const rule = rules.find(item => path.endsWith(`/rules/${item.id}`))
    if (rule) return route.fulfill(respond({ ...rule, draft: null, latest_version: rule.effective_version }))
    if (path.endsWith('/ledger')) {
      const snapshot = completed && !empty ? makeLedgerSnapshot({ trade_date: tradeDate,
        rules: versions, assessment: null, complete: false, confirmed_rule_ids: [versions[0]!.rule_id],
        evaluations: versions.map((rule, i) => ({ rule_id: rule.rule_id, rule_name: rule.name,
          confirmed: i === 0, assessment: i === 0 ? 'complied' : null, complete: i === 0, issues: [], warnings: [],
        })),
      }) : null
      return route.fulfill(respond(makeLedgerContext(snapshot, { rules: empty ? [] : versions })))
    }
    return route.continue()
  })

  await loginAsDebugUser(page, request, 'debug_normal')
  await page.goto('/stocks')
  await expect(page.getByLabel('有待打卡交易纪律')).toBeVisible()
  const userMenu = page.getByTestId('app-topbar-surface').getByRole('button', { name: '用户中心', exact: true })
  await userMenu.click()
  const card = page.getByTestId('trade-discipline-quick-card')
  await expect(card).toContainText('0/2')
  const trend = card.locator('article').filter({ hasText: '趋势纪律' })
  await trend.getByRole('button', { name: '今日无操作', exact: true }).click()
  const confirmation = page.getByRole('dialog', { name: '确认今日无操作', exact: true })
  await expect(confirmation).toContainText('其他规则的打卡状态不变')
  await confirmation.getByRole('button', { name: '取消', exact: true }).click()
  expect(submitted).toEqual([])
  await trend.getByRole('button', { name: '今日无操作', exact: true }).click()
  await confirmation.getByRole('button', { name: '确认打卡', exact: true }).click()
  await expect(trend).toContainText('已履约')
  await expect(card).toContainText('1/2')
  expect(submitted).toEqual([{ rule_id: 'quick-rule-1', trade_date: tradeDate }])
  const defensive = card.locator('article').filter({ hasText: '防守纪律' })
  await expect(defensive).toContainText('待打卡')
  await defensive.getByRole('button', { name: '去打卡', exact: true }).click()
  await expect(page).toHaveURL(/\/trade-discipline\?tab=checkin&rule_ref=quick-rule-2&trade_date=2026-08-21/)
  const records = page.getByTestId('trade-ledger-workspace').getByTestId('ledger-rule-record')
  await expect(records.filter({ hasText: '防守纪律' })).toContainText('本规则尚未确认打卡')
  await userMenu.click()
  await expect(card.getByRole('button', { name: '查看规则', exact: true })).toHaveCount(0)
  await trend.getByRole('button', { name: '查看记录', exact: true }).click()
  await expect(page).toHaveURL(/rule_ref=quick-rule-1/)
  await expect(records.filter({ hasText: '趋势纪律' })).toContainText('已履约')

  // 当前契约仅在没有生效规则时提供规则入口，保留原测试的规则管理导航目标。
  empty = true
  await page.reload()
  await userMenu.click()
  await expect(card).toContainText('还没有生效的交易规则')
  await card.getByRole('button', { name: '查看规则', exact: true }).click()
  await expect(page).toHaveURL(/\/trade-discipline\?tab=rules/)
  await expect(page.getByRole('button', { name: '规则管理', exact: true })).toHaveAttribute('aria-pressed', 'true')
  expect(issues).toEqual([])
})
