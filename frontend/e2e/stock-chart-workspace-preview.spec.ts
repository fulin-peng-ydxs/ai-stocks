import { expect, test } from '@playwright/test'
import { collectConsoleIssues } from './helpers/console'

test('多图工作区三种可见数量、局部错误、主题和键盘高度可重复验收', async ({ page }) => {
  const consoleIssues = collectConsoleIssues(page)

  await page.goto('/e2e/fixtures/stock-chart-workspace-preview.html')

  const panels = page.locator('[data-panel-key]')
  const separators = page.getByRole('separator')
  await expect(panels).toHaveCount(3)
  await expect(separators).toHaveCount(2)
  await expect(page.getByText('K线（前复权）', { exact: true })).toBeVisible()
  await expect(page.getByText('量能', { exact: true })).toBeVisible()
  await expect(page.getByText('MACD（12,26,9·前复权）', { exact: true })).toBeVisible()

  await page.getByTestId('mode-two').click()
  await expect(panels).toHaveCount(2)
  await expect(separators).toHaveCount(1)
  await expect(page.getByTestId('ratio')).toHaveText('75% · 25%')

  await page.getByTestId('mode-one').click()
  await expect(panels).toHaveCount(1)
  await expect(separators).toHaveCount(0)
  await expect(page.getByTestId('ratio')).toHaveText('100%')

  await page.getByTestId('mode-three').click()
  await page.getByTestId('theme-toggle').click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.getByTestId('macd-error-toggle').click()
  await expect(page.locator('[data-state="error"]')).toContainText('MACD 加载失败')

  const firstSeparator = page.getByRole('separator', {
    name: '调整K线（前复权）与下一幅图高度',
  })
  await firstSeparator.press('ArrowUp')
  await expect(page.getByTestId('ratio')).toHaveText('58% · 22% · 20%')

  expect(await page.evaluate(() =>
    document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  )).toBe(true)
  expect(consoleIssues).toEqual([])
})

test('根级显示比例变化后 K 线光标仍命中同一数据点', async ({ page }) => {
  await page.goto('/e2e/fixtures/stock-chart-workspace-preview.html')
  const canvas = page.locator('[data-panel-key="kline"] .stock-chart-panel__canvas')
  const date = page.locator('[data-panel-key="kline"] .stock-chart-panel__date')

  const hoverAtRelativePosition = async (scale: number) => {
    await page.evaluate((nextScale) => {
      document.documentElement.style.setProperty('--app-display-scale', String(nextScale))
      window.dispatchEvent(new Event('resize'))
    }, scale)
    await page.waitForTimeout(250)
    const box = await canvas.boundingBox()
    expect(box).not.toBeNull()
    await page.mouse.move(box!.x + box!.width * 0.55, box!.y + box!.height * 0.55)
    await expect(date).not.toHaveText('')
    return date.textContent()
  }

  const baseline = await hoverAtRelativePosition(1)
  expect(await hoverAtRelativePosition(0.8)).toBe(baseline)
  expect(await hoverAtRelativePosition(0.94)).toBe(baseline)
  expect(await hoverAtRelativePosition(1.2)).toBe(baseline)
})
