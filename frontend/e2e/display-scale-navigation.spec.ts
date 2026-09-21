import { expect, test, type Locator, type Page } from '@playwright/test'

async function expectVisualCenterTargets(page: Page, locator: Locator): Promise<void> {
  const targetMatches = await locator.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    const target = document.elementFromPoint(
      rect.left + rect.width / 2,
      rect.top + rect.height / 2,
    )
    return target === element || element.contains(target)
  })
  expect(targetMatches).toBe(true)
}

test('双层顶栏跨屏但比例不变时重建真实点击命中层', async ({ page }) => {
  await page.goto('/e2e/fixtures/display-scale-navigation-preview.html')
  const navigation = page.getByRole('navigation', { name: '二级导航' })
  const board = page.getByRole('button', { name: '每日榜单' })
  const sectors = page.getByRole('button', { name: '板块行情' })
  await expect(navigation).toHaveAttribute('data-display-scale', '73')

  await expectVisualCenterTargets(page, sectors)
  await sectors.click({ position: { x: 20, y: 15 } })
  await expect(page.getByTestId('current-route')).toHaveText('/sectors')

  const originalRevision = Number(
    await navigation.getAttribute('data-display-geometry-revision'),
  )
  await page.evaluate(() => {
    Object.defineProperty(window.screen, 'availLeft', {
      configurable: true,
      value: (Number(window.screen.availLeft) || 0) + 1920,
    })
    window.dispatchEvent(new Event('focus'))
  })
  await expect(navigation).toHaveAttribute(
    'data-display-geometry-revision',
    String(originalRevision + 1),
  )
  await expect(navigation).toHaveAttribute('data-display-scale', '73')

  await expectVisualCenterTargets(page, board)
  await board.click({ position: { x: 20, y: 15 } })
  await expect(page.getByTestId('current-route')).toHaveText('/board')
})
