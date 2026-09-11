import { AUTO_SCALE_RESPONSIVE_EXPONENT_DEFAULT } from './displayScalePolicy'
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
  balanced: {
    key: 'balanced',
    name: '澄空蓝',
    description: '明亮蓝色信号与中性黑白表面构成的统一研究空间。',
    tokens: tokens(
      { cardRadius: 10, controlRadius: 6, pageGap: 14, cardPadding: 18, tableCellPaddingY: 10 },
      {
        primary: '#1677ff', success: '#0ea968', warning: '#f58a07', danger: '#f04438',
        marketUp: '#f66055', marketDown: '#1ec96e',
        pageBg: THEME_SURFACE_SPECS.light.pageBg,
        surfaceBg: THEME_SURFACE_SPECS.light.surfaceBg,
        surfaceHover: '#f3f3f3',
        border: '#e5e5e5', borderStrong: '#c9c9c9',
        text: '#44464d', textStrong: '#17181c', textMuted: '#73757d',
        activeBg: '#efeff0', submenuBg: THEME_SURFACE_SPECS.light.sidebarBg,
        shadow: 'rgba(20, 24, 32, 0.10)',
      },
      {
        primary: '#3b8cff', success: '#3ecf8e', warning: '#f5a623', danger: '#ff6b66',
        marketUp: '#ff7a72', marketDown: '#3fdd90',
        pageBg: THEME_SURFACE_SPECS.dark.pageBg,
        surfaceBg: THEME_SURFACE_SPECS.dark.surfaceBg,
        surfaceHover: '#292929',
        border: '#353535', borderStrong: '#545454',
        text: '#d2d2d2', textStrong: '#f4f4f4', textMuted: '#9a9a9a',
        activeBg: '#303030', submenuBg: THEME_SURFACE_SPECS.dark.sidebarBg,
        shadow: 'rgba(0, 0, 0, 0.42)',
      },
    ),
    componentDefaults: { density: 'standard', tableSize: 'standard', filterDefaultExpanded: true, drawerSize: 'md' },
    responsiveDefaults: { pageGap: 14, reflowBreakpoint: 1024, autoScaleResponsiveExponent: AUTO_SCALE_RESPONSIVE_EXPONENT_DEFAULT },
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
