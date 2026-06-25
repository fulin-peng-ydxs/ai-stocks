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
  professional: {
    key: 'professional',
    name: '专业后台',
    description: '克制的中性蓝灰后台风格，作为默认预设。',
    tokens: tokens(
      { cardRadius: 4, controlRadius: 6, pageGap: 12, cardPadding: 16, tableCellPaddingY: 10 },
      {
        primary: '#409eff', success: '#2f9e44', warning: '#d97706', danger: '#dc2626',
        pageBg: '#f5f7fa', surfaceBg: '#ffffff', surfaceHover: '#eef1f6',
        border: '#e4e7ed', borderStrong: '#d0d5dd',
        text: '#4b5563', textStrong: '#1f2937', textMuted: '#8a94a6',
        activeBg: '#ecf3ff', submenuBg: '#eef1f6', shadow: 'rgba(31, 41, 55, 0.10)',
      },
      {
        primary: '#409eff', success: '#2f9e44', warning: '#d97706', danger: '#dc2626',
        pageBg: '#000000', surfaceBg: '#11151d', surfaceHover: '#1a2030',
        border: '#20283a', borderStrong: '#2a3346',
        text: '#c9d1d9', textStrong: '#ffffff', textMuted: '#5a6371',
        activeBg: '#202a3d', submenuBg: '#050709', shadow: 'rgba(0, 0, 0, 0.42)',
      },
    ),
    componentDefaults: { density: 'standard', tableSize: 'standard', filterDefaultExpanded: true, drawerSize: 'md' },
    responsiveDefaults: { pageGap: 12, reflowBreakpoint: 1024 },
  },
  government: {
    key: 'government',
    name: '政务稳重',
    description: '深红和沉稳蓝灰组合，强调边界、层级和可读性。',
    tokens: tokens(
      { cardRadius: 2, controlRadius: 4, pageGap: 12, cardPadding: 16, tableCellPaddingY: 10 },
      {
        primary: '#b91c1c', success: '#15803d', warning: '#b45309', danger: '#dc2626',
        pageBg: '#f4f5f7', surfaceBg: '#ffffff', surfaceHover: '#eef0f3',
        border: '#dcdfe6', borderStrong: '#c4c9d2',
        text: '#44474d', textStrong: '#1f2329', textMuted: '#868c96',
        activeBg: '#fbeaea', submenuBg: '#eceef1', shadow: 'rgba(31, 35, 41, 0.10)',
      },
      {
        primary: '#b91c1c', success: '#15803d', warning: '#b45309', danger: '#dc2626',
        pageBg: '#060708', surfaceBg: '#151719', surfaceHover: '#202326',
        border: '#34383f', borderStrong: '#4b5563',
        text: '#d7dde5', textStrong: '#ffffff', textMuted: '#7b8492',
        activeBg: '#352126', submenuBg: '#090b0d', shadow: 'rgba(0, 0, 0, 0.38)',
      },
    ),
    componentDefaults: { density: 'standard', tableSize: 'standard', filterDefaultExpanded: true, drawerSize: 'md' },
    responsiveDefaults: { pageGap: 12, reflowBreakpoint: 1024 },
  },
  technology: {
    key: 'technology',
    name: '科技分析',
    description: '青蓝高亮和清爽界面，适合行情与分析工作台。',
    tokens: tokens(
      { cardRadius: 6, controlRadius: 6, pageGap: 12, cardPadding: 15, tableCellPaddingY: 9 },
      {
        primary: '#0891b2', success: '#16a34a', warning: '#ca8a04', danger: '#e11d48',
        pageBg: '#eef3f8', surfaceBg: '#ffffff', surfaceHover: '#e6eef6',
        border: '#d4e0ea', borderStrong: '#a9c3d6',
        text: '#334155', textStrong: '#0f172a', textMuted: '#64748b',
        activeBg: '#d6f1f7', submenuBg: '#e6eef5', shadow: 'rgba(8, 145, 178, 0.12)',
      },
      {
        primary: '#06b6d4', success: '#22c55e', warning: '#eab308', danger: '#f43f5e',
        pageBg: '#020617', surfaceBg: '#0f172a', surfaceHover: '#172554',
        border: '#1e3a5f', borderStrong: '#2563eb',
        text: '#cbd5e1', textStrong: '#f8fafc', textMuted: '#64748b',
        activeBg: '#0e7490', submenuBg: '#020617', shadow: 'rgba(6, 182, 212, 0.18)',
      },
    ),
    componentDefaults: { density: 'compact', tableSize: 'compact', filterDefaultExpanded: false, drawerSize: 'lg' },
    responsiveDefaults: { pageGap: 12, reflowBreakpoint: 1100 },
  },
  finance: {
    key: 'finance',
    name: '金融数据',
    description: '高密表格与红绿数据色，偏交易终端气质。',
    tokens: tokens(
      { cardRadius: 2, controlRadius: 4, pageGap: 8, cardPadding: 14, tableCellPaddingY: 7 },
      {
        primary: '#dc2626', success: '#16a34a', warning: '#d97706', danger: '#dc2626',
        pageBg: '#f5f5f5', surfaceBg: '#ffffff', surfaceHover: '#efefef',
        border: '#e0e0e0', borderStrong: '#cccccc',
        text: '#3f3f46', textStrong: '#18181b', textMuted: '#71717a',
        activeBg: '#fdeaea', submenuBg: '#ededed', shadow: 'rgba(0, 0, 0, 0.10)',
      },
      {
        primary: '#ef4444', success: '#16a34a', warning: '#f59e0b', danger: '#ef4444',
        pageBg: '#000000', surfaceBg: '#101114', surfaceHover: '#1b1c20',
        border: '#2b2f36', borderStrong: '#3f4652',
        text: '#d4d4d8', textStrong: '#fafafa', textMuted: '#71717a',
        activeBg: '#371c1c', submenuBg: '#050505', shadow: 'rgba(239, 68, 68, 0.12)',
      },
    ),
    componentDefaults: { density: 'compact', tableSize: 'compact', filterDefaultExpanded: false, drawerSize: 'md' },
    responsiveDefaults: { pageGap: 8, reflowBreakpoint: 1024 },
  },
  'high-contrast': {
    key: 'high-contrast',
    name: '高对比',
    description: '更强文字与边框对比，优先保证可访问性。',
    tokens: tokens(
      { cardRadius: 2, controlRadius: 4, pageGap: 14, cardPadding: 16, tableCellPaddingY: 11 },
      {
        primary: '#1d4ed8', success: '#15803d', warning: '#b45309', danger: '#b91c1c',
        pageBg: '#ffffff', surfaceBg: '#ffffff', surfaceHover: '#e8e8e8',
        border: '#4b5563', borderStrong: '#1f2937',
        text: '#111827', textStrong: '#000000', textMuted: '#374151',
        activeBg: '#dbeafe', submenuBg: '#f3f4f6', shadow: 'rgba(0, 0, 0, 0.20)',
      },
      {
        primary: '#60a5fa', success: '#4ade80', warning: '#facc15', danger: '#fb7185',
        pageBg: '#000000', surfaceBg: '#050505', surfaceHover: '#1f2937',
        border: '#6b7280', borderStrong: '#d1d5db',
        text: '#f3f4f6', textStrong: '#ffffff', textMuted: '#cbd5e1',
        activeBg: '#1d4ed8', submenuBg: '#000000', shadow: 'rgba(255, 255, 255, 0.12)',
      },
    ),
    componentDefaults: { density: 'standard', tableSize: 'standard', filterDefaultExpanded: true, drawerSize: 'md' },
    responsiveDefaults: { pageGap: 14, reflowBreakpoint: 1024 },
  },
}

export const DEFAULT_LAYOUT_PRESET: LayoutPresetKey = 'professional'

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
