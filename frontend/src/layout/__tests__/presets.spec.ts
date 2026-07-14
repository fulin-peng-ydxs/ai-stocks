import { describe, expect, it } from 'vitest'
import { DEFAULT_LAYOUT_PRESET, getLayoutPreset, LAYOUT_PRESETS, validateLayoutPreset } from '../presets'
import { blendHex, rgbaFromHex, THEME_SURFACE_SPECS } from '../themeSurfaces'
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

function rgb(hex: string): [number, number, number] {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return [NaN, NaN, NaN]
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

/** 红蓝通道差值用于防止日曜环境底色漂向米黄、香槟或金色。 */
function goldBias(hex: string): number {
  const [r, , b] = rgb(hex)
  return r - b
}

function colorDistance(a: string, b: string): number {
  const [ar, ag, ab] = rgb(a)
  const [br, bg, bb] = rgb(b)
  return Math.hypot(ar - br, ag - bg, ab - bb)
}

function channelSpread(hex: string): number {
  const channels = rgb(hex)
  return Math.max(...channels) - Math.min(...channels)
}

function relativeLuminance(hex: string): number {
  const channels = rgb(hex).map((value) => {
    const normalized = value / 255
    return normalized <= 0.03928
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
}

function contrast(a: string, b: string): number {
  const light = Math.max(relativeLuminance(a), relativeLuminance(b))
  const dark = Math.min(relativeLuminance(a), relativeLuminance(b))
  return (light + 0.05) / (dark + 0.05)
}

describe('布局风格预设（M2 / M9 双模式）', () => {
  it('内置三套金融科技预设完整可用，light/dark 两套 token 均合法', () => {
    expect(Object.keys(LAYOUT_PRESETS).sort()).toEqual([
      'balanced',
      'daylight',
      'nocturne',
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

  it('三套预设共用 6px 控件圆角，主题切换不改变按钮与输入的基础形态', () => {
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      for (const mode of MODES) {
        expect(preset.tokens[mode].controlRadius, `${preset.key}.${mode}`).toBe(6)
      }
    }
  })

  it('三套预设的工作台画布/表面与登录交互区/登录卡片可见色同源', () => {
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      for (const mode of MODES) {
        const spec = THEME_SURFACE_SPECS[preset.key][mode]
        expect(preset.tokens[mode].pageBg, `${preset.key}.${mode} page`).toBe(spec.pageBg)
        expect(preset.tokens[mode].surfaceBg, `${preset.key}.${mode} surface`)
          .toBe(spec.surfaceBg)
        expect(spec.surfaceBg, `${preset.key}.${mode} card composite`)
          .toBe(blendHex(spec.cardBg, spec.pageBg, spec.cardAlpha))
        expect(rgbaFromHex(spec.cardBg, spec.cardAlpha), `${preset.key}.${mode} login card css`)
          .toMatch(/^rgba\(\d+, \d+, \d+, 0\.\d+\)$/)
      }
    }
  })

  it('白天模式文字在浅底上保持深色（对比度基本盘）', () => {
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      const bg = luminance(preset.tokens.light.surfaceBg)
      const text = luminance(preset.tokens.light.text)
      expect(bg - text, `${preset.key} light 文字/卡片对比`).toBeGreaterThan(90)
    }
  })

  it('日曜以铂金银灰和蓝宝石交互与夜航形成稳定差异', () => {
    for (const mode of MODES) {
      const daylight = LAYOUT_PRESETS.daylight.tokens[mode]
      const nocturne = LAYOUT_PRESETS.nocturne.tokens[mode]
      expect(goldBias(daylight.pageBg), `${mode} 环境底色无暖金偏色`)
        .toBeLessThanOrEqual(0)
      expect(colorDistance(daylight.primary, nocturne.primary), `${mode} 主交互色差异`)
        .toBeGreaterThan(60)
    }
    expect(luminance(LAYOUT_PRESETS.daylight.tokens.light.pageBg), '白天高照度')
      .toBeGreaterThan(luminance(LAYOUT_PRESETS.nocturne.tokens.light.pageBg) + 5)
  })

  it('日曜双模式的正文、弱文字和主按钮保持 WCAG AA 对比度', () => {
    for (const mode of MODES) {
      const daylight = LAYOUT_PRESETS.daylight.tokens[mode]
      expect(contrast(daylight.text, daylight.surfaceBg), `${mode} 正文`)
        .toBeGreaterThanOrEqual(4.5)
      expect(contrast(daylight.textMuted, daylight.surfaceBg), `${mode} 弱文字`)
        .toBeGreaterThanOrEqual(4.5)
      expect(contrast(daylight.primary, '#ffffff'), `${mode} 主按钮`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('晨昏夜间沿用登录页既有深蓝黑基准，并保持暖石墨边界', () => {
    const balanced = LAYOUT_PRESETS.balanced.tokens.dark
    const nocturne = LAYOUT_PRESETS.nocturne.tokens.dark
    expect(balanced.pageBg, '主页画布对齐登录交互区').toBe('#07131d')
    expect(balanced.surfaceBg, '主页表面对齐登录卡片可见色').toBe('#0a1a26')
    expect(luminance(balanced.surfaceBg), '基础表面明度')
      .toBeLessThan(luminance(nocturne.surfaceBg))
    expect(channelSpread(balanced.border), '暖石墨边界')
      .toBeLessThan(channelSpread(nocturne.border) / 2)
    expect(contrast(balanced.textMuted, balanced.surfaceBg), '弱文字可读性')
      .toBeGreaterThanOrEqual(4.5)
  })

  it('未知或旧预设回落到默认晨昏', () => {
    expect(getLayoutPreset('nope').key).toBe(DEFAULT_LAYOUT_PRESET)
  })

  it('预设只包含 token、组件默认和响应式默认，不携带页面结构', () => {
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      expect('slots' in preset).toBe(false)
      expect('archetype' in preset).toBe(false)
    }
  })
})
