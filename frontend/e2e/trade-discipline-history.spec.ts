import { expect, test } from '@playwright/test'
import type { RuleVersionDetail } from '../src/api/tradeDiscipline'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { installLedgerUiCalendar, makeLedgerContext, makeLedgerSnapshot } from './helpers/tradeDiscipline'

test.use({ actionTimeout: 15_000 })

test('账户日结历史可筛选、只读回看旧修订并修正最新记录后保留筛选', async ({ page, request }) => {
  const issues = collectConsoleIssues(page)
  const tradeDate = '2026-08-21'
  await installLedgerUiCalendar(page, tradeDate)
  let currentRevision = 2
  let note = '盘后复核'
  const queries: string[] = []
  const version: RuleVersionDetail = {
    rule_id: 'e2e-rule-1', version_no: 3, name: 'E2E 趋势纪律', capital: '100000',
    stock_rules: [{ detail_id: 'sr-1', name: '龙头', max_capital: '50000', content: '只做趋势龙头', display_order: 1, enabled: true }],
    action_rules: [{ detail_id: 'ar-1', name: '突破买入', action_type: 'buy', action_subtype: 'open_position', content: '放量突破后执行', display_order: 1, enabled: true }],
  }
  const snapshot = (revision = currentRevision, reviewNote = revision < 2 ? '首次复盘' : note) => makeLedgerSnapshot({
    trade_date: tradeDate, revision_no: revision, rules: [version], assessment: 'breached',
    review_note: reviewNote, evaluations: [{ rule_id: version.rule_id, rule_name: version.name,
      assessment: 'breached', complete: true, issues: ['偏离既定计划'], warnings: [] }],
  })
  const rule = { id: version.rule_id, name: version.name, status: 'active', latest_version_no: 3,
    management_status: 'active', latest_management_event: null, has_pending_management_action: false,
    effective_status: 'active', effective_event_seq: 1, effective_from_trade_date: tradeDate,
    effective_version: version }
  const response = (data: unknown) => ({ contentType: 'application/json', body: JSON.stringify({ code: 0, msg: 'ok', data }) })

  // 界面接线改用账户日结 DTO；不模拟已冻结的旧 checkin 写接口成功。
  await page.route('**/api/trade-discipline/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname
    if (path.endsWith('/rules') && req.method() === 'GET') return route.fulfill(response([rule]))
    if (path.endsWith(`/rules/${version.rule_id}`)) return route.fulfill(response({ ...rule, draft: null, latest_version: version }))
    if (path.endsWith('/summary')) return route.fulfill(response({ trade_date: tradeDate, total: 1, completed: 1, pending: 0,
      rules: [{ rule_id: version.rule_id, rule_name: version.name, version_no: 3, checkin_id: 'ledger-day',
        current_revision_no: currentRevision, status: 'amended', assessment: 'breached', no_operation: true }] }))
    if (path.endsWith('/ledger')) return route.fulfill(response(makeLedgerContext(snapshot())))
    if (path.endsWith('/ledger/history')) {
      queries.push(url.search)
      return route.fulfill(response({ total: 1, list: [{ trade_date: tradeDate, current_revision_no: currentRevision, snapshot: snapshot() }] }))
    }
    if (path.includes('/ledger/revisions/')) {
      const revision = Number(path.split('/').at(-1))
      return route.fulfill(response({ trade_date: tradeDate, current_revision_no: currentRevision,
        revision_no: revision, snapshot: snapshot(revision) }))
    }
    if (path.endsWith('/ledger/preview')) return route.fulfill(response(snapshot(currentRevision, req.postDataJSON().review_note)))
    if (path.endsWith('/ledger/days') && req.method() === 'POST') {
      const payload = req.postDataJSON()
      expect(payload.expected_revision).toBe(2)
      expect(payload.trade_date).toBe(tradeDate)
      expect(payload.events).toEqual([])
      expect(payload.review_note).toBe('盘后复核（修正）')
      note = payload.review_note
      currentRevision += 1
      return route.fulfill(response(snapshot()))
    }
    return route.continue()
  })

  await loginAsDebugUser(page, request, 'debug_normal')
  await page.goto(`/trade-discipline?tab=history&trade_date=${tradeDate}`)
  const workspace = page.getByTestId('trade-ledger-workspace')
  await workspace.getByRole('button', { name: /^高级搜索/ }).click()
  const assessment = workspace.locator('[data-search-field="assessment"]').getByRole('combobox')
  await assessment.press('ArrowDown')
  await page.getByRole('option', { name: '未履约', exact: true }).click()
  await expect.poll(() => queries.some(query => query.includes('assessment=breached'))).toBe(true)
  await page.getByTestId(`ledger-history-${tradeDate}`).press('Enter')
  const drawer = page.getByRole('dialog', { name: '交易日记录', exact: true })
  await expect(drawer.getByTestId('ledger-record')).toContainText('偏离既定计划')
  await drawer.getByText('E2E 趋势纪律 · v3', { exact: true }).click()
  await expect(drawer).toContainText('只做趋势龙头')
  await drawer.getByLabel('历史修订', { exact: true }).press('ArrowDown')
  await page.getByRole('option', { name: 'r1', exact: true }).click()
  await expect(drawer.getByTestId('ledger-record')).toContainText('首次复盘')
  await expect(drawer.getByRole('button', { name: '前往修正最新记录' })).toHaveCount(0)
  await drawer.getByLabel('历史修订', { exact: true }).press('ArrowDown')
  await page.getByRole('option', { name: 'r2', exact: true }).click()
  await drawer.getByRole('button', { name: '前往修正最新记录' }).click()
  await expect(drawer).not.toBeVisible()
  const save = workspace.getByRole('button', { name: '提交修正', exact: true })
  await expect(save).toBeVisible()
  await expect(save).toBeDisabled()
  await workspace.getByLabel('复盘备注（选填）').fill('盘后复核（修正）')
  await expect(save).toBeEnabled()
  await save.click()
  await expect(workspace.getByTestId('ledger-record')).toContainText('盘后复核（修正）')
  await page.getByRole('button', { name: '历史记录', exact: true }).click()
  await expect(workspace.locator('[data-search-field="assessment"]')).toContainText('未履约')
  await expect.poll(() => queries.at(-1)).toContain('assessment=breached')
  const row = workspace.getByRole('row').filter({ has: page.getByTestId(`ledger-history-${tradeDate}`) })
  await expect(row.getByRole('cell').last()).toHaveText('3')
  expect(issues).toEqual([])
})
