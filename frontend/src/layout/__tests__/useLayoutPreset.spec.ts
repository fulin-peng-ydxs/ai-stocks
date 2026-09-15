// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { useTheme } from '@/composables/useTheme'
import { LAYOUT_PRESETS } from '../presets'
import { blendHex, rgbChannelsFromHex } from '../themeSurfaces'
import {
  setLayoutPreset,
  setPresetCatalog,
  setPresetOverrides,
  setRuntimePresetSources,
  useLayoutPreset,
} from '../useLayoutPreset'
import type { ThemeMode } from '../schema'

const COLOR_LEVELS = [3, 5, 7, 8, 9] as const
const SEMANTIC_COLORS = ['primary', 'success', 'warning', 'danger'] as const

describe('视觉预设运行时 Element Plus 色阶', () => {
  const { isDark } = useTheme()

  afterEach(() => {
    isDark.value = false
    setPresetCatalog([{ key: 'balanced', name: '澄空蓝', description: '默认预设' }])
    setPresetOverrides({})
    document.documentElement.removeAttribute('style')
    document.documentElement.removeAttribute('data-layout-preset')
    document.documentElement.removeAttribute('data-layout-mode')
    localStorage.clear()
  })

  it('所有预设和明暗模式同步覆盖基础色、RGB、派生色与按下态', () => {
    for (const [presetKey, preset] of Object.entries(LAYOUT_PRESETS)) {
      for (const mode of ['light', 'dark'] as ThemeMode[]) {
        isDark.value = mode === 'dark'
        setLayoutPreset(presetKey)
        const tokens = preset.tokens[mode]
        const quietTarget = mode === 'dark' ? tokens.surfaceBg : '#ffffff'
        const activeTarget = mode === 'dark' ? '#ffffff' : '#000000'

        for (const name of SEMANTIC_COLORS) {
          const color = tokens[name]
          expect(document.documentElement.style.getPropertyValue(`--el-color-${name}`))
            .toBe(color)
          expect(document.documentElement.style.getPropertyValue(`--el-color-${name}-rgb`))
            .toBe(rgbChannelsFromHex(color))
          for (const level of COLOR_LEVELS) {
            expect(document.documentElement.style.getPropertyValue(`--el-color-${name}-light-${level}`))
              .toBe(blendHex(color, quietTarget, 1 - level / 10))
          }
          expect(document.documentElement.style.getPropertyValue(`--el-color-${name}-dark-2`))
            .toBe(blendHex(color, activeTarget, 0.8))
        }
        expect(document.documentElement.style.getPropertyValue('--el-color-error'))
          .toBe(document.documentElement.style.getPropertyValue('--el-color-danger'))
        for (const level of COLOR_LEVELS) {
          expect(document.documentElement.style.getPropertyValue(`--el-color-error-light-${level}`))
            .toBe(document.documentElement.style.getPropertyValue(`--el-color-danger-light-${level}`))
        }
        expect(document.documentElement.style.getPropertyValue('--el-color-error-dark-2'))
          .toBe(document.documentElement.style.getPropertyValue('--el-color-danger-dark-2'))
        expect(document.documentElement.style.getPropertyValue('--page-settings-seg-bg'))
          .toBe(tokens.surfaceHover)
        expect(document.documentElement.style.getPropertyValue('--app-section-bg'))
          .toBe(tokens.surfaceHover)
        expect(document.documentElement.style.getPropertyValue('--page-settings-seg-hover-bg'))
          .toBe(tokens.activeBg)
        expect(document.documentElement.style.getPropertyValue('--page-settings-seg-active-bg'))
          .toBe(mode === 'dark'
            ? blendHex(tokens.activeBg, tokens.textStrong, 0.88)
            : tokens.surfaceBg)
      }
    }
  })

  it('澄空蓝夜间同步生成蓝色派生色，不回退 Element Plus 默认色板', () => {
    isDark.value = true
    setLayoutPreset('balanced')

    expect(document.documentElement.style.getPropertyValue('--el-color-primary')).toBe('#3b8cff')
    expect(document.documentElement.style.getPropertyValue('--el-color-primary-light-5')).toBe('#29528b')
    expect(document.documentElement.style.getPropertyValue('--el-color-primary-light-5')).not.toBe('#2a598a')
    expect(document.documentElement.style.getPropertyValue('--el-color-error'))
      .toBe(document.documentElement.style.getPropertyValue('--el-color-danger'))
  })

  it('忽略历史非法颜色覆盖，运行时不生成 NaN CSS 变量', () => {
    setPresetOverrides({
      balanced: {
        'tokens.dark.primary': '#fff',
        'tokens.dark.surfaceBg': 'navy',
      },
    })
    isDark.value = true
    setLayoutPreset('balanced')

    expect(document.documentElement.style.getPropertyValue('--el-color-primary')).toBe('#3b8cff')
    expect(document.documentElement.style.cssText).not.toContain('NaN')
  })

  it('历史文字覆盖破坏亮度层级时整对回退到内置 token', () => {
    const invalidOverrides: Array<Record<string, string | number>> = [
      { 'tokens.dark.textMuted': '#c9d0d3' },
      { 'tokens.dark.text': '#8899aa', 'tokens.dark.textMuted': '#8899aa' },
    ]

    for (const overrides of invalidOverrides) {
      setPresetOverrides({ balanced: overrides })
      isDark.value = true
      setLayoutPreset('balanced')

      expect(document.documentElement.style.getPropertyValue('--el-text-color-regular'))
        .toBe('#d2d2d2')
      expect(document.documentElement.style.getPropertyValue('--el-text-color-disabled'))
        .toBe('#9a9a9a')
    }
  })

  it('后端预设更新强调色但不能改变固定基础表面，并递增主题修订版本', () => {
    const { themeRevision } = useLayoutPreset()
    setLayoutPreset('balanced')
    const beforeOverride = themeRevision.value

    setPresetOverrides({
      balanced: {
        'tokens.light.primary': '#7c3aed',
        'tokens.light.surfaceBg': '#f2f5f8',
      },
    })

    expect(themeRevision.value).toBe(beforeOverride + 1)
    expect(document.documentElement.style.getPropertyValue('--el-color-primary')).toBe('#7c3aed')
    expect(document.documentElement.style.getPropertyValue('--el-bg-color')).toBe('#ffffff')
    expect(document.documentElement.style.getPropertyValue('--chrome-bg')).toBe('#fcfcfc')
  })

  it('启用的后端自定义预设可被选择并真实驱动强调色', () => {
    setPresetCatalog([
      { key: 'balanced', name: '澄空蓝', description: '默认预设' },
      { key: 'custom-red', name: '信号红', description: '自定义强调色' },
    ])
    setPresetOverrides({
      'custom-red': {
        'tokens.light.primary': '#e5484d',
        'tokens.light.pageBg': '#fff1f1',
      },
    })
    setLayoutPreset('custom-red')

    const { activePresetKey, options } = useLayoutPreset()
    expect(activePresetKey.value).toBe('custom-red')
    expect(options.value.map((option) => option.value)).toEqual(['balanced', 'custom-red'])
    expect(document.documentElement.dataset.layoutPreset).toBe('custom-red')
    expect(document.documentElement.style.getPropertyValue('--el-color-primary')).toBe('#e5484d')
    expect(document.documentElement.style.getPropertyValue('--el-bg-color-page')).toBe('#ffffff')
  })

  it('公开外观目录缓存自定义预设并让登录页与系统页消费同一强调色', () => {
    const { themeRevision } = useLayoutPreset()
    const beforeInstall = themeRevision.value
    setRuntimePresetSources([
      {
        key: 'balanced',
        name: '澄空蓝',
        description: '默认预设',
        config: { values: { 'tokens.light.primary': '#1677ff' } },
      },
      {
        key: 'custom-purple',
        name: '星云紫',
        description: '新增颜色预设',
        config: {
          values: {
            'tokens.light.primary': '#7c3aed',
            'tokens.dark.primary': '#a78bfa',
          },
        },
      },
    ])
    expect(themeRevision.value).toBe(beforeInstall + 1)
    setLayoutPreset('custom-purple')

    expect(useLayoutPreset().options.value.map((option) => option.value))
      .toEqual(['balanced', 'custom-purple'])
    expect(document.documentElement.style.getPropertyValue('--shell-accent')).toBe('#7c3aed')
    expect(document.documentElement.style.getPropertyValue('--brand-icon-start'))
      .toBe(blendHex('#7c3aed', '#ffffff', 0.62))
    expect(document.documentElement.style.getPropertyValue('--brand-icon-end'))
      .toBe(blendHex('#7c3aed', '#000000', 0.8))
    expect(localStorage.getItem('ai-stocks:layout-preset')).toBe('custom-purple')
    expect(localStorage.getItem('ai-stocks:layout-preset-catalog:v1')).toContain('custom-purple')

    isDark.value = true
    setLayoutPreset('custom-purple')
    expect(document.documentElement.style.getPropertyValue('--shell-accent')).toBe('#a78bfa')
    expect(document.documentElement.style.getPropertyValue('--brand-icon-start'))
      .toBe(blendHex('#a78bfa', '#ffffff', 0.62))
    expect(document.documentElement.style.getPropertyValue('--brand-icon-end'))
      .toBe(blendHex('#a78bfa', '#ffffff', 0.8))
    expect(document.documentElement.style.getPropertyValue('--el-bg-color-page')).toBe('#171717')
  })
})
