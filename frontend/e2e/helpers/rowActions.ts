import type { Locator, Page } from '@playwright/test'

/** 共享行操作会按实际宽度收进“更多”；始终从指定行打开同一具名操作。 */
export async function rowAction(page: Page, row: Locator, name: string): Promise<Locator> {
  const inline = row.getByRole('button', { name, exact: true })
  if (await inline.isVisible()) return inline
  await row.getByRole('button', { name: '更多', exact: true }).click()
  return page.getByRole('menuitem', { name, exact: true })
}
