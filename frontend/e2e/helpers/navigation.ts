import type { Locator, Page } from '@playwright/test'
import { expect } from '@playwright/test'

const COLD_ROUTE_READY_TIMEOUT = 20_000

/** 等待 Vite 冷编译、路由装载和页面语义标题同时就绪。 */
export async function openPageAndWaitForHeading(
  page: Page,
  path: string,
  heading: string,
): Promise<void> {
  await page.goto(path)
  await expect(page.getByRole('heading', { name: heading })).toBeVisible({
    timeout: COLD_ROUTE_READY_TIMEOUT,
  })
}

/** 等待命名表格及其异步内容完成渲染，复用冷启动并发下的统一超时口径。 */
export async function waitForNamedTableCells(
  page: Page,
  tableName: string,
  cellText: string | RegExp,
): Promise<Locator> {
  const cells = page
    .getByRole('table', { name: tableName })
    .getByRole('cell')
    .filter({ hasText: cellText })
  await expect(cells.first()).toBeVisible({ timeout: COLD_ROUTE_READY_TIMEOUT })
  return cells
}
