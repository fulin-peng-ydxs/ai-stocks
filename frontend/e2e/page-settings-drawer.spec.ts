import { expect, test } from '@playwright/test'
import {
  getUserPreference,
  loginAsDebugUser,
  saveUserPreference,
} from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'

test.describe('页面设置抽屉', () => {
  test('组件分页字段自动进入用户管理抽屉并驱动实际查询', async ({ page, request }) => {
    const consoleIssues = collectConsoleIssues(page)
    await loginAsDebugUser(page, request, 'debug_system')

    // 拦截本用例的布局用户层保存，验证点击链路而不污染固定调试账号。
    await page.route('**/api/layout/users/user-manage', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      await route.fulfill({
        json: {
          code: 0,
          msg: 'ok',
          data: { userId: 'debug_system', pageKey: 'user-manage', config: { schemaVersion: 1, values: {} } },
        },
      })
    })

    let queriedSize: string | null = null
    page.on('request', (req) => {
      const url = new URL(req.url())
      if (url.pathname === '/api/users' && url.searchParams.has('size')) queriedSize = url.searchParams.get('size')
    })

    await page.goto('/system/users')
    await page.getByTestId('page-settings-trigger').click()
    const drawer = page.getByTestId('page-settings-drawer')
    await expect(drawer).toBeVisible()
    const pageSizeGroup = drawer.getByRole('group', { name: '用户列表：每页条数' })
    await expect(pageSizeGroup).toBeVisible()

    const target = pageSizeGroup.locator('button[aria-pressed="false"]').first()
    const targetSize = (await target.textContent())?.trim() ?? ''
    await target.click()
    await expect.poll(() => queriedSize).toBe(targetSize)
    expect(consoleIssues).toEqual([])
  })

  test('恢复默认会清除抽屉自身用户偏好并回到默认尺寸', async ({ page, request }) => {
    const consoleIssues = collectConsoleIssues(page)

    const auth = await loginAsDebugUser(page, request, 'debug_normal')
    await saveUserPreference(request, auth, {
      scope: 'global',
      prefKey: 'settings-drawer',
      value: { size: 'lg', defaultCollapsed: ['layout'] },
    })

    await page.goto('/board')
    await page.getByTestId('page-settings-trigger').click()

    const drawer = page.getByTestId('page-settings-drawer')
    await expect(drawer).toBeVisible()
    await expect(page.getByTestId('drawer-size-lg')).toHaveClass(/active/)
    await expect(drawer).toContainText('个人')
    await expect.poll(async () => (
      Math.round(await drawer.evaluate((node) => node.getBoundingClientRect().width))
    )).toBe(440)

    await page.getByTestId('page-settings-reset').click()

    await expect(page.getByTestId('drawer-size-md')).toHaveClass(/active/)
    await expect(page.getByTestId('drawer-size-lg')).not.toHaveClass(/active/)
    await expect(drawer).toContainText('默认')
    await expect.poll(async () => (
      Math.round(await drawer.evaluate((node) => node.getBoundingClientRect().width))
    )).toBe(360)
    await expect.poll(async () => (
      await getUserPreference(request, auth, { scope: 'global', prefKey: 'settings-drawer' })
    )).toEqual({})

    expect(consoleIssues).toEqual([])
  })
})
