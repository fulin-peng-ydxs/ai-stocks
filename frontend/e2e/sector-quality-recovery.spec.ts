import { expect, test } from '@playwright/test'

import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { openPageAndWaitForHeading } from './helpers/navigation'

test.describe('板块数据质量恢复', () => {
  test('立即质检提交后防重复操作并按失败终态反馈', async ({
    page,
    request,
  }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium-standard', '质检任务交互聚焦验证仅在标准视口执行')
    const consoleIssues = collectConsoleIssues(page)
    await loginAsDebugUser(page, request, 'debug_system')
    let submitCount = 0
    let taskReads = 0

    await page.route('**/api/data/quality?*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0,
          msg: 'ok',
          data: { summary: [], total: 0, page: 1, size: 20, list: [] },
        }),
      })
    })
    await page.route('**/api/data/tasks', async (route) => {
      submitCount += 1
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, msg: 'ok', data: { task_id: 'e2e-verify' } }),
      })
    })
    await page.route('**/api/data/tasks/e2e-verify', async (route) => {
      taskReads += 1
      const running = taskReads === 1
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0,
          msg: 'ok',
          data: {
            id: 'e2e-verify',
            task_type: 'verify',
            status: running ? 'running' : 'failed',
            progress: running ? 0.3 : 1,
            message: running ? '全市场四层数据质检中…' : '质检扫描失败',
            result: null,
          },
        }),
      })
    })

    await openPageAndWaitForHeading(page, '/data/quality', '数据质量')
    const verifyButton = page.getByRole('button', { name: '立即质检', exact: true })
    await verifyButton.click()

    await expect(verifyButton).toBeDisabled()
    await expect(page.getByText('质检任务已提交，可在「数据采集 › 任务中心」查看进度', {
      exact: true,
    })).toBeVisible()
    expect(submitCount).toBe(1)

    await expect(page.getByText('质检扫描失败', { exact: true })).toBeVisible()
    await expect(verifyButton).toBeEnabled()
    expect(taskReads).toBeGreaterThanOrEqual(2)
    expect(consoleIssues).toEqual([])
  })

  test('主动刷新失败后错误态接管列表，不继续展示旧质量记录', async ({
    page,
    request,
  }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium-standard', '四态接管聚焦验证仅在标准视口执行')
    const consoleIssues = collectConsoleIssues(page)
    await loginAsDebugUser(page, request, 'debug_system')
    let failRefresh = false

    await page.route('**/api/data/quality?*', async (route) => {
      if (failRefresh) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ code: 5000, msg: '服务暂时不可用，请稍后重试', data: null }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0,
          msg: 'ok',
          data: {
            summary: [{ issue_type: 'board_index_gap', n: 1 }],
            total: 1,
            page: 1,
            size: 20,
            list: [{
              id: 92001,
              code: '309121',
              name: '旧质量记录',
              trade_date: '2026-08-20',
              issue_type: 'board_index_gap',
              severity: 'mid',
              status: 'open',
              detail: '刷新前的旧内容',
              detected_at: '2026-08-20 09:30:00',
              resolved_at: null,
            }],
          },
        }),
      })
    })

    await openPageAndWaitForHeading(page, '/data/quality', '数据质量')
    await expect(page.getByText('旧质量记录', { exact: true })).toBeVisible()

    failRefresh = true
    await page.getByRole('button', { name: '刷新', exact: true }).click()

    const mainRegion = page.getByTestId('layout-grow-region')
    await expect(mainRegion.getByText('数据质量刷新失败', { exact: true })).toBeVisible()
    await expect(mainRegion.getByText('服务暂时不可用，请稍后重试', { exact: true })).toBeVisible()
    await expect(page.getByText('旧质量记录', { exact: true })).toHaveCount(0)
    expect(consoleIssues).toEqual([])
  })

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
