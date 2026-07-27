import { expect, test } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'

test.describe('列表操作组件', () => {
  test.beforeEach(async ({ page, request }) => {
    await loginAsDebugUser(page, request, 'debug_system')
    await page.goto('/system/users')
  })

  test('更多菜单无布局跳动并支持 Escape 与点击外部关闭', async ({ page }) => {
    await expect(page.getByRole('table', { name: '用户列表', exact: true }))
      .toHaveAttribute('aria-busy', 'false')
    const actions = page.getByTestId('user-row-actions-debug_system')
    const more = page.getByTestId('user-row-actions-debug_system-more')
    await expect(actions).toBeVisible()
    await expect(more).toBeVisible()

    // 以真实点击目标为准；仅滚动外层 group 时，固定列按钮仍可能被表格底部遮挡，
    // Playwright 会在 click 前二次滚动，导致把测试驱动滚动误判为菜单布局跳动。
    await more.scrollIntoViewIfNeeded()
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
    for (const key of ['width', 'height'] as const) {
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
