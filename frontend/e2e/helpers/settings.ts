import type { Locator } from '@playwright/test'

/** 分组标题与帮助/收展按钮已独立，显式展开目标分组，不依赖标题聚合文本。 */
export async function expandSettingsSection(drawer: Locator, section: string): Promise<void> {
  const expand = drawer.getByRole('button', { name: `${section}：展开下级分组`, exact: true })
  if (await expand.isVisible()) await expand.click()
}
