// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import {
  initAppNavigation,
  setNavigationMode,
  useAppNavigation,
} from '@/composables/useAppNavigation'

describe('应用导航布局偏好', () => {
  beforeEach(() => localStorage.clear())

  it('默认使用侧栏标签模式，并持久化用户选择', () => {
    initAppNavigation()
    expect(useAppNavigation().navigationMode.value).toBe('sidebar-tabs')
    setNavigationMode('dual-topbar')
    expect(localStorage.getItem('ai-stocks-navigation-mode')).toBe('dual-topbar')
  })

  it('初始化时恢复合法选择，非法值回落默认模式', () => {
    localStorage.setItem('ai-stocks-navigation-mode', 'dual-topbar')
    initAppNavigation()
    expect(useAppNavigation().navigationMode.value).toBe('dual-topbar')

    localStorage.setItem('ai-stocks-navigation-mode', 'unknown')
    initAppNavigation()
    expect(useAppNavigation().navigationMode.value).toBe('sidebar-tabs')
  })
})
