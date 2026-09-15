import { describe, expect, it } from 'vitest'
import { resolveMenuPageTitle } from '../useMenuPageTitle'
import type { MenuTreeNode } from '@/utils/permission'

const menus: MenuTreeNode[] = [{
  index: 'system',
  title: '系统管理',
  children: [{ index: '/system/layout/presets', title: '视觉预设' }],
}]

describe('resolveMenuPageTitle', () => {
  it('优先使用菜单名称并覆盖静态路由标题', () => {
    expect(resolveMenuPageTitle(
      menus,
      '/system/layout/presets',
      '旧路由标题',
    )).toBe('视觉预设')
  })

  it('详情子路由继承最长匹配菜单并统一拼接状态', () => {
    expect(resolveMenuPageTitle(
      [{ index: '/training', title: '实战训练' }],
      '/training/session/1',
      '盘感训练',
      { suffix: '进行中' },
    )).toBe('实战训练 · 进行中')
  })

  it('菜单尚未加载时回退路由标题', () => {
    expect(resolveMenuPageTitle([], '/screen', '策略筛选')).toBe('策略筛选')
  })
})
