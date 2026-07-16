// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { useTheme } from '@/composables/useTheme'
import { LAYOUT_PRESETS } from '../presets'
import { blendHex, rgbChannelsFromHex } from '../themeSurfaces'
import { setLayoutPreset } from '../useLayoutPreset'
import type { LayoutPresetKey, ThemeMode } from '../schema'

const COLOR_LEVELS = [3, 5, 7, 8, 9] as const
const SEMANTIC_COLORS = ['primary', 'success', 'warning', 'danger'] as const

describe('布局预设运行时 Element Plus 色阶', () => {
  const { isDark } = useTheme()

  afterEach(() => {
    isDark.value = false
    document.documentElement.removeAttribute('style')
    document.documentElement.removeAttribute('data-layout-preset')
    document.documentElement.removeAttribute('data-layout-mode')
    localStorage.clear()
  })

  it('所有预设和明暗模式同步覆盖基础色、RGB、派生色与按下态', () => {
    for (const [presetKey, preset] of Object.entries(LAYOUT_PRESETS)) {
      for (const mode of ['light', 'dark'] as ThemeMode[]) {
        isDark.value = mode === 'dark'
        setLayoutPreset(presetKey as LayoutPresetKey)
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
      }
    }
  })

  it('晨昏夜间禁用主按钮使用香槟金派生色，不回退 Element Plus 默认蓝色', () => {
    isDark.value = true
    setLayoutPreset('balanced')

    expect(document.documentElement.style.getPropertyValue('--el-color-primary')).toBe('#c4a364')
    expect(document.documentElement.style.getPropertyValue('--el-color-primary-light-5')).toBe('#675f45')
    expect(document.documentElement.style.getPropertyValue('--el-color-primary-light-5')).not.toBe('#2a598a')
    expect(document.documentElement.style.getPropertyValue('--el-color-error'))
      .toBe(document.documentElement.style.getPropertyValue('--el-color-danger'))
  })
})
