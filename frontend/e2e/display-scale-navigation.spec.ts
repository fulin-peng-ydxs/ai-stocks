import { expect, test, type Locator, type Page } from '@playwright/test'

async function expectVisualCenterTargets(page: Page, locator: Locator): Promise<void> {
  const hitTest = await locator.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    const target = document.elementFromPoint(
      rect.left + rect.width / 2,
      rect.top + rect.height / 2,
    )
    return {
      matches: target === element || element.contains(target),
      element: {
        tag: element.tagName,
        className: element.className,
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      },
      target: target && {
        tag: target.tagName,
        className: (target as HTMLElement).className,
        text: target.textContent,
      },
    }
  })
  expect(hitTest.matches, JSON.stringify(hitTest)).toBe(true)
}

test('双层顶栏跨屏且比例不变时仍保持原生点击命中', async ({ page }) => {
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
  await expect.poll(async () => Number(
    await navigation.getAttribute('data-display-geometry-revision'),
  )).toBeGreaterThan(originalRevision)
  await expect.poll(async () => Number(
    await navigation.getAttribute('data-display-geometry-revision'),
  )).toBeGreaterThanOrEqual(originalRevision + 2)
  await expect(navigation).toHaveAttribute('data-display-scale', '73')
  await expect.poll(() => page.locator('#app').evaluate((element) => ({
    zoom: getComputedStyle(element).zoom,
    transform: getComputedStyle(element).transform,
  }))).toEqual({ zoom: '0.73', transform: 'none' })

  await expectVisualCenterTargets(page, board)
  await board.click({ position: { x: 20, y: 15 } })
  await expect(page.getByTestId('current-route')).toHaveText('/board')
})
