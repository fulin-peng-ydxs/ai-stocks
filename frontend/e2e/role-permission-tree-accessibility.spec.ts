import { expect, test } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { openPageAndWaitForHeading, waitForNamedTableCells } from './helpers/navigation'

test('角色权限树支持键盘展开并提供唯一的读屏名称', async ({ page, request }) => {
  const consoleIssues = collectConsoleIssues(page)
  await loginAsDebugUser(page, request, 'debug_system')
  await openPageAndWaitForHeading(page, '/system/roles', '角色管理')

  const activeRoleHeading = page.getByRole('heading', {
    level: 2,
    name: /系统管理员.*系统内置/,
  })
  await expect(activeRoleHeading).toBeVisible({ timeout: 20_000 })
  expect((await activeRoleHeading.textContent())?.trim().endsWith('系统内置')).toBe(true)
  const groupToggle = page.getByRole('button', { name: /已选 \d+\/\d+/ }).first()
  await expect(groupToggle).toBeVisible()
  await expect(groupToggle).toHaveAttribute('aria-controls', /permission-group-region-/)
  await expect(groupToggle).toHaveJSProperty('tabIndex', 0)

  const initialExpanded = await groupToggle.getAttribute('aria-expanded')
  await groupToggle.focus()
  await expect(groupToggle).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(groupToggle).toHaveAttribute(
    'aria-expanded',
    initialExpanded === 'true' ? 'false' : 'true',
  )
  await page.keyboard.press('Space')
  await expect(groupToggle).toHaveAttribute('aria-expanded', initialExpanded ?? 'false')
  if (initialExpanded !== 'true') {
    await page.keyboard.press('Enter')
    await expect(groupToggle).toHaveAttribute('aria-expanded', 'true')
  }

  const resourceTriggers = page.getByRole('button', { name: /功能权限 \d+\/\d+/ })
  await expect(resourceTriggers.first()).toBeVisible()
  const accessibleNames = await resourceTriggers.evaluateAll((buttons) =>
    buttons.map((button) => button.getAttribute('aria-label') ?? ''))
  expect(accessibleNames.length).toBeGreaterThan(0)
  expect(accessibleNames.every((name) => name.includes('功能权限'))).toBe(true)
  expect(new Set(accessibleNames).size).toBe(accessibleNames.length)

  const firstResourceTrigger = resourceTriggers.first()
  const resourceRegionId = await firstResourceTrigger.getAttribute('aria-controls')
  expect(resourceRegionId).toBeTruthy()
  const resourceRegion = page.locator(`#${resourceRegionId}`)
  await expect(resourceRegion).toBeAttached()
  await expect(resourceRegion).toBeHidden()

  await firstResourceTrigger.click()
  await expect(resourceRegion).toBeVisible()

  const firstPermission = resourceRegion.getByRole('checkbox').first()
  await expect(firstPermission).toHaveAccessibleName(/\S+/)
  expect(consoleIssues).toEqual([])
})

test('菜单和功能点的系统内置标签统一后置', async ({ page, request }) => {
  const consoleIssues = collectConsoleIssues(page)
  await loginAsDebugUser(page, request, 'debug_system')
  await openPageAndWaitForHeading(page, '/system/menus', '菜单与功能')

  await page.getByRole('treeitem', { name: '用户管理', exact: true }).click()

  const menuTitle = page.getByRole('heading', {
    level: 2,
    name: /用户管理.*系统内置/,
  })
  await expect(menuTitle).toBeVisible()
  expect((await menuTitle.textContent())?.trim().endsWith('系统内置')).toBe(true)

  const builtinResourceCodes = await waitForNamedTableCells(
    page,
    '功能点',
    /系统内置\s*$/,
  )
  const resourceTexts = await builtinResourceCodes.allTextContents()
  expect(resourceTexts.every((text) => text.trim().endsWith('系统内置'))).toBe(true)
  expect(consoleIssues).toEqual([])
})
