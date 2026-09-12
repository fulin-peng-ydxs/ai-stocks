import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { DEFAULT_LAYOUT_PRESET, getLayoutPreset, LAYOUT_PRESETS, validateLayoutPreset } from '../presets'
import {
  blendHex,
  contrastRatioFromHex,
  MIN_TEXT_HIERARCHY_LUMINANCE_DELTA,
  relativeLuminanceFromHex,
  rgbaFromHex,
  THEME_SURFACE_SPECS,
} from '../themeSurfaces'
import type { ThemeMode } from '../schema'

const MODES: ThemeMode[] = ['light', 'dark']
const TEST_DIR = dirname(fileURLToPath(import.meta.url))
const SRC_DIR = join(TEST_DIR, '../..')

/** 取 #rrggbb 的相对亮度（0~255 粗算），用于断言「白天底比夜间底亮」。 */
function luminance(hex: string): number {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return NaN
  const n = parseInt(m[1], 16)
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255
  return 0.299 * r + 0.587 * g + 0.114 * b
}

describe('布局风格预设（M2 / M9 双模式）', () => {
  it('颜色工具统一计算 WCAG 对比度并对非法颜色 fail-closed', () => {
    expect(contrastRatioFromHex('#000000', '#ffffff')).toBeCloseTo(21)
    expect(contrastRatioFromHex('#ffffff', '#ffffff')).toBe(1)
    expect(contrastRatioFromHex('invalid', '#ffffff')).toBeNaN()
  })

  it('只暴露一套澄空蓝预设，light/dark 两套 token 均合法', () => {
    expect(Object.keys(LAYOUT_PRESETS)).toEqual(['balanced'])
    expect(LAYOUT_PRESETS.balanced.name).toBe('澄空蓝')
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

  it('默认预设共用 6px 控件圆角，主题切换不改变按钮与输入的基础形态', () => {
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      for (const mode of MODES) {
        expect(preset.tokens[mode].controlRadius, `${preset.key}.${mode}`).toBe(6)
      }
    }
  })

  it('工作台画布/表面与登录统一画布/登录卡片可见色同源', () => {
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      for (const mode of MODES) {
        const spec = THEME_SURFACE_SPECS[mode]
        expect(preset.tokens[mode].pageBg, `${preset.key}.${mode} page`).toBe(spec.pageBg)
        expect(preset.tokens[mode].surfaceBg, `${preset.key}.${mode} surface`)
          .toBe(spec.surfaceBg)
        expect(preset.tokens[mode].submenuBg, `${preset.key}.${mode} sidebar`)
          .toBe(spec.sidebarBg)
        expect(spec.surfaceBg, `${preset.key}.${mode} card composite`)
          .toBe(blendHex(spec.cardBg, spec.pageBg, spec.cardAlpha))
        expect(rgbaFromHex(spec.cardBg, spec.cardAlpha), `${preset.key}.${mode} login card css`)
          .toMatch(/^rgba\(\d+, \d+, \d+, 1\)$/)
      }
    }
  })

  it('常驻信息分区使用独立语义变量并覆盖描述表标签格', () => {
    const globalCss = readFileSync(join(SRC_DIR, 'styles/global.css'), 'utf8')

    expect(globalCss).toContain('--app-section-bg: #f3f3f3')
    expect(globalCss).toContain('--app-section-bg: #292929')
    expect(globalCss).toMatch(
      /\.el-descriptions__label\.el-descriptions__cell\.is-bordered-label\s*\{\s*background-color:\s*var\(--app-section-bg\)/,
    )
  })

  it('白天模式文字在浅底上保持深色（对比度基本盘）', () => {
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      const bg = luminance(preset.tokens.light.surfaceBg)
      const text = luminance(preset.tokens.light.text)
      expect(bg - text, `${preset.key} light 文字/卡片对比`).toBeGreaterThan(90)
    }
  })

  it('所有预设的普通操作与禁用操作保持可辨文字亮度层级', () => {
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      for (const mode of MODES) {
        const tokens = preset.tokens[mode]
        const delta = Math.abs(
          relativeLuminanceFromHex(tokens.text) - relativeLuminanceFromHex(tokens.textMuted),
        )
        expect(delta, `${preset.key}.${mode} 正文/弱文字亮度差`)
          .toBeGreaterThanOrEqual(MIN_TEXT_HIERARCHY_LUMINANCE_DELTA)
      }
    }
  })

  it('预设校验拒绝正文与弱化文字亮度塌缩', () => {
    const base = LAYOUT_PRESETS.balanced
    const invalid = {
      ...base,
      tokens: {
        ...base.tokens,
        dark: { ...base.tokens.dark, textMuted: base.tokens.dark.text },
      },
    }

    expect(validateLayoutPreset(invalid)).toContain('dark.text 与 dark.textMuted 的相对亮度差不足')
  })

  it('澄空蓝双模式的正文和弱文字保持 WCAG AA 对比度', () => {
    for (const mode of MODES) {
      const preset = LAYOUT_PRESETS.balanced.tokens[mode]
      expect(contrastRatioFromHex(preset.text, preset.surfaceBg), `${mode} 正文`)
        .toBeGreaterThanOrEqual(4.5)
      expect(contrastRatioFromHex(preset.textMuted, preset.surfaceBg), `${mode} 弱文字`)
        .toBeGreaterThanOrEqual(4.5)
    }
  })

  it('澄空蓝使用参考原型的中性白天底与炭黑夜间底', () => {
    const light = LAYOUT_PRESETS.balanced.tokens.light
    const balanced = LAYOUT_PRESETS.balanced.tokens.dark
    expect(light.pageBg).toBe('#ffffff')
    expect(light.surfaceBg).toBe('#ffffff')
    expect(light.submenuBg).toBe('#fcfcfc')
    expect(light.primary).toBe('#1677ff')
    expect(balanced.pageBg, '主页画布对齐登录统一画布').toBe('#171717')
    expect(balanced.surfaceBg, '夜间主体表面必须与主页画布连续').toBe('#171717')
    expect(balanced.submenuBg, '边栏对齐原型深色表面').toBe('#1f1f1f')
    expect(balanced.primary).toBe('#3b8cff')
    expect(contrastRatioFromHex(balanced.textMuted, balanced.surfaceBg), '弱文字可读性')
      .toBeGreaterThanOrEqual(4.5)
  })

  it('页面设置抽屉保留遮光层，同时使用中性明暗内容表面', () => {
    const drawer = readFileSync(join(SRC_DIR, 'components/PageSettingsDrawer.vue'), 'utf8')
    const globalCss = readFileSync(join(SRC_DIR, 'styles/global.css'), 'utf8')

    expect(drawer).toMatch(
      /\.el-overlay\.ps-settings-modal\)\s*\{\s*background-color:\s*rgba\(0, 0, 0, 0\.32\) !important;/,
    )
    expect(globalCss).toContain('--drawer-bg: #ffffff')
    expect(globalCss).toContain('--page-settings-section-bg: #ffffff')
    expect(globalCss).toContain('--drawer-bg: #171717')
    expect(globalCss).toContain('--drawer-card-bg: #171717')
    expect(globalCss).toContain('--page-settings-bg: #171717')
  })

  it('二级导航与工作标签栏共享随预设强调色变化的背景渐变', () => {
    const globalCss = readFileSync(join(SRC_DIR, 'styles/global.css'), 'utf8')
    const topNavigation = readFileSync(join(SRC_DIR, 'components/TopNavigation.vue'), 'utf8')
    const workspaceTabs = readFileSync(join(SRC_DIR, 'components/WorkspaceTabs.vue'), 'utf8')

    expect(globalCss).toContain(
      '--chrome-context-bar-bg: linear-gradient(90deg, color-mix(in srgb, var(--chrome-bg) 94%, var(--shell-accent) 6%), var(--chrome-bg))',
    )
    expect(topNavigation).toContain('background: var(--chrome-context-bar-bg)')
    expect(workspaceTabs).toContain('background: var(--chrome-context-bar-bg)')
  })

  it('核心主题与品牌入口不残留偏暖底色或旧护眼色板', () => {
    const sources = [
      'App.vue',
      'components/BrandMark.vue',
      'views/LoginView.vue',
      'styles/global.css',
    ].map((path) => readFileSync(join(SRC_DIR, path), 'utf8').toLowerCase())
    const forbiddenWarmColors = [
      '#fff7f4',
      '#fff7d8',
      '#d8b76e',
      '#9fc1ce',
      '#e2e2df',
      '#c9c9c5',
      '#f2f2f0',
    ]

    for (const color of forbiddenWarmColors) {
      expect(sources.join('\n'), color).not.toContain(color)
    }
  })

  it('未知或旧预设回落到默认澄空蓝', () => {
    expect(getLayoutPreset('nope').key).toBe(DEFAULT_LAYOUT_PRESET)
    expect(getLayoutPreset('daylight').key).toBe(DEFAULT_LAYOUT_PRESET)
    expect(getLayoutPreset('nocturne').key).toBe(DEFAULT_LAYOUT_PRESET)
  })

  it('预设只包含 token、组件默认和响应式默认，不携带页面结构', () => {
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      expect('slots' in preset).toBe(false)
      expect('archetype' in preset).toBe(false)
    }
  })

  it('预设管理页复用统一运行时目录入口，方案标签文档登记所有消费页', () => {
    const view = readFileSync(join(SRC_DIR, 'views/layout/LayoutPresetsView.vue'), 'utf8')
    const design = readFileSync(join(SRC_DIR, '../../DESIGN.md'), 'utf8')

    expect(view).toContain('setRuntimePresetSources(enabledPresets)')
    expect(view).not.toContain('setPresetCatalog')
    expect(view).not.toContain('setPresetOverrides')
    expect(design).toMatch(
      /AssetProfileLabel[\s\S]*消费页包括[^|\n]*StockDetailView/,
    )
  })

  it('金融涨跌色为独立 token 且感知亮度恒高于同名主体信号色一档', () => {
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      for (const mode of MODES) {
        const t = preset.tokens[mode]
        // 独立 token，不与主体色合并
        expect(t.marketUp, `${mode}.marketUp`).not.toBe(t.danger)
        expect(t.marketDown, `${mode}.marketDown`).not.toBe(t.success)
        // 感知亮度：金融色恒高于同名主体信号色（涨红>危险红、跌绿>成功绿）
        expect(relativeLuminanceFromHex(t.marketUp), `${mode} 涨红>危险红`)
          .toBeGreaterThan(relativeLuminanceFromHex(t.danger))
        expect(relativeLuminanceFromHex(t.marketDown), `${mode} 跌绿>成功绿`)
          .toBeGreaterThan(relativeLuminanceFromHex(t.success))
      }
    }
  })

  it('亮色模式信号色为提彩鲜亮色，不回退到暗哑色板', () => {
    const t = LAYOUT_PRESETS.balanced.tokens.light
    // 旧哑光色板（深色/Element 默认灰调）禁回归
    const staleDull = ['#168f63', '#d97706', '#d9363e', '#52c41a', '#d48806', '#e6a23c', '#f56c6c', '#67c23a']
    for (const key of ['success', 'warning', 'danger', 'marketUp', 'marketDown'] as const) {
      expect(staleDull, `light.${key}=${t[key]} 不得为旧哑光色`).not.toContain(t[key].toLowerCase())
    }
    // 鲜亮信号色白底仍需可读（成功/危险/涨红对比度下限）
    expect(contrastRatioFromHex(t.danger, '#ffffff'), '危险红白底').toBeGreaterThanOrEqual(3)
    expect(contrastRatioFromHex(t.success, '#ffffff'), '成功绿白底').toBeGreaterThanOrEqual(2.4)
    expect(contrastRatioFromHex(t.warning, '#ffffff'), '警告橙白底').toBeGreaterThanOrEqual(2)
  })

  it('金融/状态/评分色无 global.css 或组件内平行硬编码色板', () => {
    const globalCss = readFileSync(join(SRC_DIR, 'styles/global.css'), 'utf8')
    // market/app-warning/app-danger/score 事实源已移交预设，global.css 不再硬编码具体色值
    expect(globalCss).not.toMatch(/--market-up-color:\s*#/)
    expect(globalCss).not.toMatch(/--market-down-color:\s*#/)
    expect(globalCss).not.toMatch(/--app-warning-text:\s*#/)
    expect(globalCss).not.toMatch(/--app-danger-text:\s*#/)
    expect(globalCss).not.toMatch(/--score-high-text:\s*#/)
    expect(globalCss).not.toMatch(/--score-mid-text:\s*#/)
    // 内联 style 颜色组件经统一快照消费，无私有色阶
    const subScoreBars = readFileSync(join(SRC_DIR, 'components/SubScoreBars.vue'), 'utf8')
    expect(subScoreBars).toContain('useStatusColorPalette')
    expect(subScoreBars).not.toMatch(/#[0-9a-fA-F]{6}/)
  })
})
