import { expect, test } from '@playwright/test'

import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { openPageAndWaitForHeading } from './helpers/navigation'

test.describe('板块数据质量恢复', () => {
  test('成分采集不完整可发起重采并在任务成功后刷新收敛', async ({
    page,
    request,
  }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium-standard', '质量修复链路仅在标准视口执行')
    const consoleIssues = collectConsoleIssues(page)
    await loginAsDebugUser(page, request, 'debug_system')
    let fixed = false

    await page.route('**/api/data/quality/91001/fix', async (route) => {
      fixed = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, msg: 'ok', data: { task_id: 'e2e-sector-fix' } }),
      })
    })
    await page.route('**/api/data/tasks/e2e-sector-fix', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0,
          msg: 'ok',
          data: {
            id: 'e2e-sector-fix',
            status: 'done',
            message: '板块成分重采完成',
            result: { ok: true },
          },
        }),
      })
    })
    await page.route('**/api/data/quality?*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0,
          msg: 'ok',
          data: {
            summary: fixed ? [] : [{ issue_type: 'board_member_incomplete', n: 1 }],
            total: fixed ? 0 : 1,
            page: 1,
            size: 20,
            list: fixed ? [] : [{
              id: 91001,
              code: '309121',
              name: 'AI PC',
              trade_date: null,
              issue_type: 'board_member_incomplete',
              severity: 'mid',
              status: 'open',
              detail: '成分分页未完整返回',
              detected_at: '2026-08-11 09:30:00',
              resolved_at: null,
            }],
          },
        }),
      })
    })

    await openPageAndWaitForHeading(page, '/data/quality', '数据质量')
    await expect(page.getByText('AI PC', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '重采成分', exact: true }).click()
    await expect(page.getByText('AI PC', { exact: true })).toHaveCount(0)
    await expect(page.getByText('板块成分重采完成', { exact: true })).toBeVisible()
    expect(fixed).toBe(true)
    expect(consoleIssues).toEqual([])
  })
})
