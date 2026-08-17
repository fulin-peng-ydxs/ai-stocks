// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { createLayout, useLayoutConfig, type PageLayout } from '../index'

function testLayout(pageKey = 'remote-demo'): PageLayout {
  const layout = createLayout('list', pageKey)
  layout.slots.push({ id: 'settings', component: 'settings-drawer', region: 'overlay', order: 99 })
  return layout
}

describe('useLayoutConfig 远端用户层', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('远端用户层覆盖 localStorage fallback', () => {
    localStorage.setItem(
      'ai-stocks:layout:remote-demo',
      JSON.stringify({ schemaVersion: 1, values: { density: 'compact' } }),
    )
    const config = useLayoutConfig(testLayout())
    expect(config.valueOf('density')).toBe('compact')

    config.applyUserConfig({ schemaVersion: 1, values: { density: 'comfortable' } })

    expect(config.valueOf('density')).toBe('comfortable')
    expect(config.sourceOf('density')).toBe('user')
    expect(config.exportUserConfig().values.density).toBe('comfortable')
  })

  it('拉取中发生的本地编辑不会被远端返回覆盖', () => {
    const config = useLayoutConfig(testLayout())
    config.setKnob('density', 'comfortable')

    const applied = config.applyUserConfig(
      { schemaVersion: 1, values: { density: 'compact' } },
      { preserveDirty: true },
    )

    expect(applied.preservedDirty).toBe(true)
    expect(config.valueOf('density')).toBe('comfortable')
    expect(config.exportUserConfig().values.density).toBe('comfortable')
  })

  it('组件用户配置导出为后端 layout_user_config values 路径', () => {
    const config = useLayoutConfig(testLayout())
    config.setComponentKnob('table', 'pageSize', 50)

    expect(config.componentValueOf('table', 'pageSize')).toBe(50)
    expect(config.exportUserConfig().values['slots.table.config.pageSize']).toBe(50)
  })

  it('旧本地 settings-drawer 尺寸和默认折叠不自动进入页面用户层', () => {
    localStorage.setItem(
      'ai-stocks:layout-cc:remote-demo',
      JSON.stringify({
        schemaVersion: 1,
        values: {
          'slots.settings.config.size': 'lg',
          'slots.settings.config.defaultCollapsed': ['layout'],
          'slots.table.config.pageSize': 100,
        },
      }),
    )

    const config = useLayoutConfig(testLayout())

    expect(config.componentValueOf('settings', 'size')).toBe('md')
    expect(config.componentValueOf('settings', 'defaultCollapsed')).toEqual([])
    expect(config.componentValueOf('table', 'pageSize')).toBe(100)
    expect(config.exportUserConfig().values).not.toHaveProperty('slots.settings.config.size')
    expect(config.exportUserConfig().values).not.toHaveProperty('slots.settings.config.defaultCollapsed')
  })

  it('专用 user 持久化目标不依赖固定 slotId，并拒绝旧远端值与直接写入', () => {
    const layout = testLayout('custom-drawer-slot')
    const settings = layout.slots.find((slot) => slot.id === 'settings')!
    settings.id = 'preferencesOverlay'
    const config = useLayoutConfig(layout)

    config.applyUserConfig({
      values: {
        'slots.preferencesOverlay.config.size': 'lg',
        'slots.preferencesOverlay.config.defaultCollapsed': ['layout'],
      },
    })

    expect(config.componentValueOf('preferencesOverlay', 'size')).toBe('md')
    expect(config.componentValueOf('preferencesOverlay', 'defaultCollapsed')).toEqual([])
    expect(config.exportUserConfig().values).not.toHaveProperty('slots.preferencesOverlay.config.size')
    expect(() => config.setComponentKnob('preferencesOverlay', 'size', 'sm'))
      .toThrow('必须通过全局偏好入口修改')
  })
})
