import type { LayoutPreset, LayoutPresetKey, PresetTokens, StyleTokenConfig, ThemeMode } from './schema'

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
    description: '冷银白与雾蓝构成的明亮研究空间，适合白天长时间阅读。',
    tokens: tokens(
      { cardRadius: 10, controlRadius: 8, pageGap: 14, cardPadding: 18, tableCellPaddingY: 10 },
      {
        primary: '#2c708d', success: '#238568', warning: '#a8732a', danger: '#c64f57',
        pageBg: '#edf3f5', surfaceBg: '#fbfcfc', surfaceHover: '#e4edef',
        border: '#d2dee2', borderStrong: '#adc1c9',
        text: '#435c67', textStrong: '#102d3b', textMuted: '#7b919a',
        activeBg: '#dce9ed', submenuBg: '#e8eff1', shadow: 'rgba(24, 58, 72, 0.11)',
      },
      {
        primary: '#79b4c9', success: '#55b895', warning: '#d2a157', danger: '#e5757c',
        pageBg: '#18252c', surfaceBg: '#22323a', surfaceHover: '#2c4049',
        border: '#3c525c', borderStrong: '#687f89',
        text: '#d1dfe4', textStrong: '#f5f9fa', textMuted: '#92a8b1',
        activeBg: '#31505c', submenuBg: '#1b2a31', shadow: 'rgba(1, 12, 17, 0.34)',
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
      { cardRadius: 8, controlRadius: 7, pageGap: 12, cardPadding: 17, tableCellPaddingY: 10 },
      {
        primary: '#227f9d', success: '#248364', warning: '#9d6b28', danger: '#c7515d',
        pageBg: '#e8eef1', surfaceBg: '#f8fafb', surfaceHover: '#dde8ec',
        border: '#c7d5db', borderStrong: '#9fb5bf',
        text: '#3b5360', textStrong: '#0b2635', textMuted: '#6f8792',
        activeBg: '#d4e7ed', submenuBg: '#e1e9ed', shadow: 'rgba(9, 40, 54, 0.13)',
      },
      {
        primary: '#62bad2', success: '#52c29a', warning: '#d5a85e', danger: '#ef747e',
        pageBg: '#071721', surfaceBg: '#0d222e', surfaceHover: '#153440',
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
    description: '海军蓝与香槟金保持明暗平衡，兼顾日间专注与夜间沉浸。',
    tokens: tokens(
      { cardRadius: 10, controlRadius: 8, pageGap: 13, cardPadding: 18, tableCellPaddingY: 10 },
      {
        primary: '#98773f', success: '#2b8769', warning: '#aa742d', danger: '#c7565e',
        pageBg: '#edf1f3', surfaceBg: '#fafcfc', surfaceHover: '#e4eaed',
        border: '#d1dade', borderStrong: '#aebdc4',
        text: '#465a64', textStrong: '#132b37', textMuted: '#7e9099',
        activeBg: '#ebe3d5', submenuBg: '#e7ecee', shadow: 'rgba(18, 40, 50, 0.12)',
      },
      {
        primary: '#c4a364', success: '#52b98f', warning: '#d4a45a', danger: '#eb747b',
        pageBg: '#0a1a25', surfaceBg: '#102631', surfaceHover: '#193540',
        border: '#304a56', borderStrong: '#687e87',
        text: '#c4d2d8', textStrong: '#f3f7f8', textMuted: '#8197a1',
        activeBg: '#3b3b34', submenuBg: '#0c202a', shadow: 'rgba(1, 10, 15, 0.42)',
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
  }
  if (!['compact', 'standard', 'comfortable'].includes(preset.componentDefaults.density)) {
    issues.push('componentDefaults.density 非法')
  }
  return issues
}
