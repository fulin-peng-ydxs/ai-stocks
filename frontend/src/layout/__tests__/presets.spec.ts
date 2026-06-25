import { describe, expect, it } from 'vitest'
import { DEFAULT_LAYOUT_PRESET, getLayoutPreset, LAYOUT_PRESETS, validateLayoutPreset } from '../presets'
import type { ThemeMode } from '../schema'

const MODES: ThemeMode[] = ['light', 'dark']

/** 取 #rrggbb 的相对亮度（0~255 粗算），用于断言「白天底比夜间底亮」。 */
function luminance(hex: string): number {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return NaN
  const n = parseInt(m[1], 16)
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255
  return 0.299 * r + 0.587 * g + 0.114 * b
}

describe('布局风格预设（M2 / M9 双模式）', () => {
  it('内置五套预设完整可用，light/dark 两套 token 均合法', () => {
    expect(Object.keys(LAYOUT_PRESETS).sort()).toEqual([
      'finance',
      'government',
      'high-contrast',
      'professional',
      'technology',
    ])
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      expect(validateLayoutPreset(preset), preset.key).toEqual([])
      for (const mode of MODES) {
        expect(preset.tokens[mode].primary, `${preset.key}.${mode}`).toMatch(/^#/)
        expect(preset.tokens[mode].pageBg, `${preset.key}.${mode}`).toMatch(/^#/)
      }
      expect(preset.componentDefaults.density).toMatch(/compact|standard|comfortable/)
    }
  })

  it('每套预设的白天底色明显亮于夜间底色（M9：两模式真实区分）', () => {
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      const light = luminance(preset.tokens.light.pageBg)
      const dark = luminance(preset.tokens.dark.pageBg)
      expect(light, `${preset.key} light.pageBg`).toBeGreaterThan(dark + 80)
    }
  })

  it('白天模式文字在浅底上保持深色（对比度基本盘）', () => {
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      const bg = luminance(preset.tokens.light.surfaceBg)
      const text = luminance(preset.tokens.light.text)
      expect(bg - text, `${preset.key} light 文字/卡片对比`).toBeGreaterThan(90)
    }
  })

  it('未知预设回落到默认专业后台', () => {
    expect(getLayoutPreset('nope').key).toBe(DEFAULT_LAYOUT_PRESET)
  })

  it('预设只包含 token、组件默认和响应式默认，不携带页面结构', () => {
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      expect('slots' in preset).toBe(false)
      expect('archetype' in preset).toBe(false)
    }
  })
})
