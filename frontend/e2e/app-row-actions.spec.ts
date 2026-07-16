import { expect, test } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'

test.describe('列表操作组件', () => {
  test.beforeEach(async ({ page, request }) => {
    await loginAsDebugUser(page, request, 'debug_system')
    await page.goto('/system/users')
  })

  test('更多菜单无布局跳动并支持 Escape 与点击外部关闭', async ({ page }) => {
    const actions = page.getByTestId('user-row-actions-debug_system')
    const more = page.getByTestId('user-row-actions-debug_system-more')
    await expect(actions).toBeVisible()
    await expect(more).toBeVisible()

    await actions.scrollIntoViewIfNeeded()
    const before = await actions.boundingBox()
    expect(before).not.toBeNull()
    await more.click()

    const menu = page.getByTestId('user-row-actions-debug_system-menu')
    const deleteAction = page.getByTestId('user-row-actions-debug_system-delete')
    await expect(menu).toBeVisible()
    await expect(deleteAction).toBeVisible()
    await expect(deleteAction).toBeDisabled()
    await expect(menu).toHaveCSS('animation-name', 'none')
    const after = await actions.boundingBox()
    expect(after).not.toBeNull()
    for (const key of ['x', 'y', 'width', 'height'] as const) {
      expect(after?.[key]).toBeCloseTo(before?.[key] ?? 0, 1)
    }

    await page.keyboard.press('Escape')
    await expect(menu).toBeHidden()

    await more.click()
    await expect(menu).toBeVisible()
    await page.getByRole('heading', { name: '用户管理' }).click()
    await expect(menu).toBeHidden()
  })
})
