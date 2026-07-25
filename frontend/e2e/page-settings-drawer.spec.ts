import { expect, test } from '@playwright/test'
import {
  getUserPreference,
  loginAsDebugUser,
  saveUserPreference,
} from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'

test.describe('页面设置抽屉', () => {
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
