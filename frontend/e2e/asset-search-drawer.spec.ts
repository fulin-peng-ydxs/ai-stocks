import { expect, test, type APIRequestContext } from '@playwright/test'
import { authenticateDebugUser, loginAsDebugUser, type E2EAuthSnapshot } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { openPageAndWaitForHeading } from './helpers/navigation'

const API_URL = process.env.E2E_API_URL || 'http://127.0.0.1:8000/api'
const EXPR = {
  op: 'AND',
  children: [{ type: 'col', field: 'is_bull_arrange', cmp: '==', value: true }],
}

async function apiCall(
  request: APIRequestContext,
  auth: E2EAuthSnapshot,
  method: 'get' | 'post' | 'delete',
  path: string,
  data?: unknown,
) {
  const resp = await request[method](`${API_URL}${path}`, {
    headers: { authorization: `Bearer ${auth.accessToken}` },
    ...(method === 'post' && data !== undefined ? { data } : {}),
  })
  const body = await resp.json().catch(() => ({}))
  return { status: resp.status(), body }
}

// R3/R5/R14 筛选页样板：搜索抽屉三来源段 + 复制为我的 + 临时只读加载查看（跨用户真实链路）。
// 数据前提（T0 dev 事实）：筛选预设全 private → 系统内置段常态为空，属于预期空态而非缺陷。
test('筛选页资产搜索抽屉：三来源、复制为我的、临时只读加载查看', async ({ page, request }, testInfo) => {
  const consoleIssues = collectConsoleIssues(page)
  const marker = `E2E搜索筛选${Date.now()}`
  const seedId = `e2e_search_${Date.now()}`
  const seeder = await authenticateDebugUser(request, 'debug_normal')
  const viewer = await authenticateDebugUser(request, 'debug_tenant_admin')

  const created = await apiCall(request, seeder, 'post', '/profiles', { id: seedId, name: marker, expression: EXPR })
  expect(created.body.code, `预置筛选方案失败：${created.body.msg || ''}`).toBe(0)
  const published = await apiCall(request, seeder, 'post', `/profiles/${seedId}/visibility`, { visibility: 'tenant' })
  expect(published.body.code, `发布预置方案失败：${published.body.msg || ''}`).toBe(0)

  try {
    await loginAsDebugUser(page, request, 'debug_tenant_admin')
    await openPageAndWaitForHeading(page, '/screen', '策略筛选')

    // 打开搜索抽屉：默认系统内置段（筛选预设全 private → 预期空态）
    await page.getByTestId('asset-profile-select-search').click()
    const drawer = page.getByTestId('asset-search-drawer')
    await expect(drawer).toBeVisible()
    await expect(drawer).toContainText('暂无系统内置筛选方案')
    // 视觉验收：等待抽屉进场动画结束、宽度稳定到语义档位 xl（560px）后再截图
    const drawerPanel = page.locator('.el-drawer', { has: drawer })
    await expect(drawerPanel).toHaveJSProperty('offsetWidth', 560)
    await testInfo.attach(`asset-search-drawer-preset-empty-${testInfo.project.name}`, {
      body: await drawerPanel.screenshot(),
      contentType: 'image/png',
    })

    // 切到租户公开段：同租户他人发布的方案可见，提供者经来源徽标 title 脱敏承载
    await drawer.getByTestId('asset-search-drawer-segment-tenant').click()
    const row = drawer.getByRole('row').filter({ hasText: marker })
    await expect(row).toBeVisible()
    await expect(row.locator('.asset-visibility-tag').first()).toHaveAttribute('title', /同租户用户/)
    await expect(row).not.toContainText('debug_normal')
    // 需求契约（合并形态）：方案类列 = 方案名称(含版本/更新时间)/来源(徽标 title 含提供者)/操作
    // 三列全部完整可见（左右边界都在抽屉可视区内），无横向滚动
    const drawerBox = await drawerPanel.boundingBox()
    expect(drawerBox, '抽屉应有可视区域').not.toBeNull()
    const drawerLeft = drawerBox!.x
    const drawerRight = drawerBox!.x + drawerBox!.width
    for (const header of ['方案名称', '来源', '操作']) {
      const cell = drawer.getByRole('columnheader', { name: header })
      await expect(cell, `列头「${header}」应渲染`).toBeVisible()
      const box = await cell.boundingBox()
      expect(box, `列头「${header}」应有可视区域`).not.toBeNull()
      expect(box!.x, `列头「${header}」左缘不应超出抽屉左边界`).toBeGreaterThanOrEqual(drawerLeft - 1)
      expect(box!.x + box!.width, `列头「${header}」右缘不应超出抽屉右边界`).toBeLessThanOrEqual(drawerRight + 1)
    }
    // 合并单元格：名称单元格次行含「更新于 + 时间」；提供者经来源徽标 title 承载
    await expect(row).toContainText('更新于')
    await expect(row.locator('.asset-visibility-tag').first()).toHaveAttribute('title', /同租户用户/)
    // 操作列 fixed="right"：核心操作完整可见
    const loadBtn = row.getByTestId('asset-search-drawer-load')
    await expect(loadBtn).toBeVisible()
    const loadBox = await loadBtn.boundingBox()
    expect(loadBox, '操作列「加载查看」应渲染').not.toBeNull()
    expect(loadBox!.x, '操作列左缘不应超出抽屉左边界').toBeGreaterThanOrEqual(drawerLeft - 1)
    expect(loadBox!.x + loadBox!.width, '操作列右缘不应超出抽屉右边界').toBeLessThanOrEqual(drawerRight + 1)
    await testInfo.attach(`asset-search-drawer-tenant-${testInfo.project.name}`, {
      body: await drawerPanel.screenshot(),
      contentType: 'image/png',
    })

    // 复制为我的：单击直接复制，「我的」下拉刷新并选中
    await row.getByTestId('asset-search-drawer-copy').click()
    const select = page.getByTestId('asset-profile-select-select')
    await expect(select).toContainText(`${marker} 副本`)
    await expect(select).toContainText('我的方案')

    // 加载查看：临时只读注入（不进「我的」、不自动跑筛选）；先关抽屉再重新打开
    await page.keyboard.press('Escape')
    await expect(drawer).toBeHidden()
    await page.getByTestId('asset-profile-select-search').click()
    await expect(drawer).toBeVisible()
    await drawer.getByTestId('asset-search-drawer-segment-tenant').click()
    const rowAgain = drawer.getByRole('row').filter({ hasText: marker })
    await expect(rowAgain).toBeVisible()
    await rowAgain.getByTestId('asset-search-drawer-load').click()
    await expect(drawer).toBeHidden()
    await expect(select).toContainText(marker)
    await expect(select).toContainText('租户公开')
    // 只读语义由来源徽标 title 承载（AssetVisibilityTag 契约）
    await expect(select.locator('.asset-visibility-tag').first()).toHaveAttribute('title', /只读/)

    expect(consoleIssues).toEqual([])
  } finally {
    // 清理：预置方案下架并删除；观察者账号删掉复制产物
    await apiCall(request, seeder, 'post', `/profiles/${seedId}/visibility`, { visibility: 'private' })
    await apiCall(request, seeder, 'delete', `/profiles/${seedId}`)
    const mine = await apiCall(request, viewer, 'get', '/profiles?source=mine')
    const items = (mine.body?.data?.items ?? mine.body?.data ?? []) as { id: string; name?: string }[]
    for (const item of Array.isArray(items) ? items : []) {
      if (item.name?.includes(marker)) {
        await apiCall(request, viewer, 'delete', `/profiles/${item.id}`)
      }
    }
  }
})
