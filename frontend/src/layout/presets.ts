import type { LayoutPreset, LayoutPresetKey, PresetTokens, StyleTokenConfig, ThemeMode } from './schema'
import {
  hasDistinctTextHierarchy,
  isHexColor,
  STYLE_COLOR_TOKEN_KEYS,
  THEME_SURFACE_SPECS,
} from './themeSurfaces'

/** 模式无关的形态/密度 token（圆角、间距、行高）：白天/夜间共用。 */
type SharedShape = Pick<StyleTokenConfig, 'cardRadius' | 'controlRadius' | 'pageGap' | 'cardPadding' | 'tableCellPaddingY'>
/** 模式相关 token（颜色 + 阴影）：白天/夜间各一套。 */
type ModeColors = Omit<StyleTokenConfig, keyof SharedShape>

/** 组装双模式 token：形态/密度共用，颜色/阴影按 light/dark 分开。 */
function tokens(shape: SharedShape, light: ModeColors, dark: ModeColors): PresetTokens {
  return { light: { ...shape, ...light }, dark: { ...shape, ...dark } }
}

export const LAYOUT_PRESETS: Record<LayoutPresetKey, LayoutPreset> = {
  daylight: {
    key: 'daylight',
    name: '日曜',
    description: '铂金银灰、蓝宝石电光与精密石墨构成的高照度研究舱。',
    tokens: tokens(
      { cardRadius: 10, controlRadius: 6, pageGap: 14, cardPadding: 18, tableCellPaddingY: 10 },
      {
        primary: '#2f5bd3', success: '#187760', warning: '#b84d3d', danger: '#c23e5a',
        pageBg: THEME_SURFACE_SPECS.daylight.light.pageBg,
        surfaceBg: THEME_SURFACE_SPECS.daylight.light.surfaceBg,
        surfaceHover: '#e9eef7',
        border: '#d3ddec', borderStrong: '#9facbf',
        text: '#40516a', textStrong: '#152137', textMuted: '#63738a',
        activeBg: '#e3e9fb', submenuBg: '#e9eef7', shadow: 'rgba(24, 43, 82, 0.12)',
      },
      {
        primary: '#496bc2', success: '#368b72', warning: '#c45f50', danger: '#d0526d',
        pageBg: THEME_SURFACE_SPECS.daylight.dark.pageBg,
        surfaceBg: THEME_SURFACE_SPECS.daylight.dark.surfaceBg,
        surfaceHover: '#2a3242',
        border: '#3a4559', borderStrong: '#65738b',
        text: '#cfd7e5', textStrong: '#f6f8fc', textMuted: '#96a3b7',
        activeBg: '#273654', submenuBg: '#11151d', shadow: 'rgba(3, 7, 16, 0.48)',
      },
    ),
    componentDefaults: { density: 'standard', tableSize: 'standard', filterDefaultExpanded: true, drawerSize: 'md' },
    responsiveDefaults: { pageGap: 12, reflowBreakpoint: 1024 },
  },
  nocturne: {
    key: 'nocturne',
    name: '夜航',
    description: '深海蓝、冷青与铂金边界，适合低照度环境和夜间复盘。',
    tokens: tokens(
      { cardRadius: 8, controlRadius: 6, pageGap: 12, cardPadding: 17, tableCellPaddingY: 10 },
      {
        primary: '#227f9d', success: '#248364', warning: '#9d6b28', danger: '#c7515d',
        pageBg: THEME_SURFACE_SPECS.nocturne.light.pageBg,
        surfaceBg: THEME_SURFACE_SPECS.nocturne.light.surfaceBg,
        surfaceHover: '#dde8ec',
        border: '#c7d5db', borderStrong: '#9fb5bf',
        text: '#3b5360', textStrong: '#0b2635', textMuted: '#6f8792',
        activeBg: '#d4e7ed', submenuBg: '#e1e9ed', shadow: 'rgba(9, 40, 54, 0.13)',
      },
      {
        primary: '#62bad2', success: '#52c29a', warning: '#d5a85e', danger: '#ef747e',
        pageBg: THEME_SURFACE_SPECS.nocturne.dark.pageBg,
        surfaceBg: THEME_SURFACE_SPECS.nocturne.dark.surfaceBg,
        surfaceHover: '#153440',
        border: '#294a58', borderStrong: '#66808b',
        text: '#bfd0d7', textStrong: '#f2f7f8', textMuted: '#8199a4',
        activeBg: '#184254', submenuBg: '#091b25', shadow: 'rgba(0, 7, 12, 0.46)',
      },
    ),
    componentDefaults: { density: 'standard', tableSize: 'standard', filterDefaultExpanded: true, drawerSize: 'md' },
    responsiveDefaults: { pageGap: 12, reflowBreakpoint: 1024 },
  },
  balanced: {
    key: 'balanced',
    name: '晨昏',
    description: '日间海军蓝、夜间沿用登录页深蓝黑，以香槟金维持克制的黑金平衡。',
    tokens: tokens(
      { cardRadius: 10, controlRadius: 6, pageGap: 13, cardPadding: 18, tableCellPaddingY: 10 },
      {
        primary: '#98773f', success: '#2b8769', warning: '#aa742d', danger: '#c7565e',
        pageBg: THEME_SURFACE_SPECS.balanced.light.pageBg,
        surfaceBg: THEME_SURFACE_SPECS.balanced.light.surfaceBg,
        surfaceHover: '#e4eaed',
        border: '#d1dade', borderStrong: '#aebdc4',
        text: '#465a64', textStrong: '#132b37', textMuted: '#7e9099',
        activeBg: '#ebe3d5', submenuBg: '#e7ecee', shadow: 'rgba(18, 40, 50, 0.12)',
      },
      {
        primary: '#c4a364', success: '#52b98f', warning: '#d4a45a', danger: '#eb747b',
        pageBg: THEME_SURFACE_SPECS.balanced.dark.pageBg,
        surfaceBg: THEME_SURFACE_SPECS.balanced.dark.surfaceBg,
        surfaceHover: '#14232a',
        border: '#343a3b', borderStrong: '#716d63',
        text: '#c9d0d3', textStrong: '#f4f1e8', textMuted: '#87949b',
        activeBg: '#302d25', submenuBg: '#081820', shadow: 'rgba(0, 0, 0, 0.5)',
      },
    ),
    componentDefaults: { density: 'standard', tableSize: 'standard', filterDefaultExpanded: true, drawerSize: 'md' },
    responsiveDefaults: { pageGap: 13, reflowBreakpoint: 1024 },
  },
}

export const DEFAULT_LAYOUT_PRESET: LayoutPresetKey = 'balanced'

export function getLayoutPreset(key: string | null | undefined): LayoutPreset {
  return LAYOUT_PRESETS[(key ?? '') as LayoutPresetKey] ?? LAYOUT_PRESETS[DEFAULT_LAYOUT_PRESET]
}

/** 取预设在指定模式下的 token 集（缺省 dark，兼容旧调用）。 */
export function presetTokens(preset: LayoutPreset, mode: ThemeMode = 'dark'): StyleTokenConfig {
  return preset.tokens[mode]
}

export function validateLayoutPreset(preset: LayoutPreset): string[] {
  const issues: string[] = []
  if (!preset.key || !preset.name) issues.push('预设必须包含 key 和 name')
  const modes: ThemeMode[] = ['light', 'dark']
  for (const mode of modes) {
    const set = preset.tokens?.[mode]
    if (!set) {
      issues.push(`预设缺少 ${mode} 模式 token`)
      continue
    }
    for (const [key, value] of Object.entries(set)) {
      if (typeof value === 'string' && !value.trim()) issues.push(`${mode}.${key} 不能为空`)
      if (typeof value === 'number' && (!Number.isFinite(value) || value < 0)) issues.push(`${mode}.${key} 必须为非负数值`)
    }
    for (const key of STYLE_COLOR_TOKEN_KEYS) {
      if (!isHexColor(set[key])) issues.push(`${mode}.${key} 必须是 #RRGGBB 颜色`)
    }
    if (isHexColor(set.text) && isHexColor(set.textMuted)
      && !hasDistinctTextHierarchy(set.text, set.textMuted)) {
      issues.push(`${mode}.text 与 ${mode}.textMuted 的相对亮度差不足`)
    }
  }
  if (!['compact', 'standard', 'comfortable'].includes(preset.componentDefaults.density)) {
    issues.push('componentDefaults.density 非法')
  }
  return issues
}
