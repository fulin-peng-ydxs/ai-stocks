import type { StyleTokenConfig, ThemeMode } from './schema'

export const STYLE_COLOR_TOKEN_KEYS = [
  'primary',
  'success',
  'warning',
  'danger',
  'marketUp',
  'marketDown',
  'pageBg',
  'surfaceBg',
  'surfaceHover',
  'border',
  'borderStrong',
  'text',
  'textStrong',
  'textMuted',
  'activeBg',
  'submenuBg',
] as const satisfies readonly (keyof StyleTokenConfig)[]

export const MIN_TEXT_HIERARCHY_LUMINANCE_DELTA = 0.06

export interface LoginSurfaceSpec {
  /** 登录页统一画布基础色，同时也是工作台 pageBg。 */
  pageBg: string
  /** 登录页品牌区基础色，同时也是工作台边栏背景。 */
  sidebarBg: string
  /** 登录卡片的原始基色；可按 cardAlpha 与画布合成。 */
  cardBg: string
  /** 登录卡片在 pageBg 上叠加时使用的透明度。 */
  cardAlpha: number
  /** 登录卡片叠加后的肉眼可见色，同时也是工作台 surfaceBg。 */
  surfaceBg: string
  /** 常驻筛选、摘要和配置分组的次级表面，不参与悬停状态。 */
  sectionBg: string
}

type RgbChannels = [number, number, number]

export function isHexColor(value: unknown): value is string {
  return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value.trim())
}

export function isStyleColorTokenKey(value: string): value is (typeof STYLE_COLOR_TOKEN_KEYS)[number] {
  return STYLE_COLOR_TOKEN_KEYS.includes(value as (typeof STYLE_COLOR_TOKEN_KEYS)[number])
}

function parseHex(hex: string): RgbChannels | null {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return null
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function toHex(channels: RgbChannels): string {
  return `#${channels
    .map((value) => Math.round(value).toString(16).padStart(2, '0'))
    .join('')}`
}

export function blendHex(foreground: string, background: string, alpha: number): string {
  const fg = parseHex(foreground)
  const bg = parseHex(background)
  if (!fg && !bg) return '#000000'
  if (!fg) return toHex(bg as RgbChannels)
  if (!bg) return toHex(fg)
  const safeAlpha = Number.isFinite(alpha) ? Math.min(1, Math.max(0, alpha)) : 1
  return toHex(fg.map((value, index) => (
    value * safeAlpha + bg[index] * (1 - safeAlpha)
  )) as RgbChannels)
}

export function rgbaFromHex(hex: string, alpha: number): string {
  const [r, g, b] = parseHex(hex) ?? [0, 0, 0]
  const safeAlpha = Number.isFinite(alpha) ? Math.min(1, Math.max(0, alpha)) : 1
  return `rgba(${r}, ${g}, ${b}, ${safeAlpha})`
}

export function rgbChannelsFromHex(hex: string): string {
  return (parseHex(hex) ?? [0, 0, 0]).join(', ')
}

export function relativeLuminanceFromHex(hex: string): number {
  const channels = parseHex(hex)
  if (!channels) return NaN
  const [r, g, b] = channels.map((value) => {
    const normalized = value / 255
    return normalized <= 0.03928
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4
  }) as RgbChannels
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** WCAG 对比度统一口径；任一颜色不是六位 hex 时返回 NaN。 */
export function contrastRatioFromHex(left: string, right: string): number {
  const leftLuminance = relativeLuminanceFromHex(left)
  const rightLuminance = relativeLuminanceFromHex(right)
  if (!Number.isFinite(leftLuminance) || !Number.isFinite(rightLuminance)) return NaN
  const light = Math.max(leftLuminance, rightLuminance)
  const dark = Math.min(leftLuminance, rightLuminance)
  return (light + 0.05) / (dark + 0.05)
}

export function hasDistinctTextHierarchy(text: string, textMuted: string): boolean {
  const delta = Math.abs(relativeLuminanceFromHex(text) - relativeLuminanceFromHex(textMuted))
  return Number.isFinite(delta) && delta >= MIN_TEXT_HIERARCHY_LUMINANCE_DELTA
}

function surface(
  pageBg: string,
  sidebarBg: string,
  cardBg: string,
  cardAlpha: number,
  sectionBg: string,
): LoginSurfaceSpec {
  return {
    pageBg,
    sidebarBg,
    cardBg,
    cardAlpha,
    surfaceBg: blendHex(cardBg, pageBg, cardAlpha),
    sectionBg,
  }
}

/**
 * 明暗模式的固定基础表面。
 * 预设只能覆盖强调色和形态，不能改变主画布、边栏、卡片与文字的中性底色；边界消费预设的统一边框角色。
 */
export const THEME_SURFACE_SPECS: Record<ThemeMode, LoginSurfaceSpec> = {
  light: surface('#fafafa', '#fcfcfc', '#ffffff', 1, '#f7f7f7'),
  dark: surface('#111111', '#1c1c1c', '#191919', 1, '#202020'),
}

export function getLoginSurfaceSpec(mode: ThemeMode): LoginSurfaceSpec {
  return THEME_SURFACE_SPECS[mode]
}

/** 背景与边界角色的唯一映射。业务组件只选角色，不自行混色或依赖组件库默认档位。 */
export function themeSurfaceVariables(tokens: StyleTokenConfig, mode: ThemeMode): Record<string, string> {
  const spec = THEME_SURFACE_SPECS[mode]
  const divider = tokens.border
  const selected = blendHex(tokens.primary, tokens.surfaceBg, 0.06)
  return {
    '--app-overlay-scrim': 'rgba(0, 0, 0, 0.32)',
    '--app-surface-canvas': spec.pageBg,
    '--app-surface-container': spec.surfaceBg,
    '--app-surface-section': spec.sectionBg,
    '--app-surface-navigation': spec.sidebarBg,
    '--app-surface-active': tokens.activeBg,
    '--app-surface-control': spec.surfaceBg,
    '--app-surface-overlay': spec.surfaceBg,
    '--app-surface-hover': tokens.surfaceHover,
    '--app-surface-selected': selected,
    '--app-border-divider': divider,
    '--app-border-default': tokens.border,
    '--app-border-strong': tokens.borderStrong,
    '--app-border-selected': tokens.primary,
    '--el-bg-color-page': spec.pageBg,
    '--el-bg-color': spec.surfaceBg,
    '--el-bg-color-overlay': spec.surfaceBg,
    '--el-fill-color-blank': spec.surfaceBg,
    '--el-fill-color': tokens.activeBg,
    '--el-fill-color-light': tokens.surfaceHover,
    '--el-fill-color-lighter': spec.sectionBg,
    '--el-fill-color-extra-light': spec.sectionBg,
    '--app-section-bg': spec.sectionBg,
    '--el-disabled-bg-color': spec.surfaceBg,
    '--el-disabled-border-color': tokens.border,
    '--el-disabled-text-color': tokens.textMuted,
    '--el-border-color': tokens.border,
    '--el-border-color-light': tokens.border,
    '--el-border-color-lighter': divider,
    '--el-border-color-extra-light': divider,
    '--el-border-color-dark': tokens.borderStrong,
    '--el-border-color-darker': tokens.borderStrong,
    '--chrome-bg': spec.sidebarBg,
    '--chrome-bg-soft': spec.surfaceBg,
    '--chrome-bg-soft-hover': tokens.surfaceHover,
    '--chrome-border': tokens.border,
    '--chrome-border-strong': tokens.borderStrong,
    '--chrome-submenu-bg': spec.sidebarBg,
    '--chrome-active-bg': tokens.activeBg,
    '--drawer-bg': spec.surfaceBg,
    '--drawer-card-bg': spec.surfaceBg,
    '--drawer-border': tokens.border,
    '--page-settings-bg': spec.surfaceBg,
    '--page-settings-border': tokens.border,
    '--page-settings-section-bg': spec.sectionBg,
    '--page-settings-section-border': tokens.border,
    '--page-settings-divider': divider,
    '--page-settings-dot-ring': spec.surfaceBg,
    '--page-settings-trigger-hover-bg': tokens.surfaceHover,
    '--page-settings-seg-bg': tokens.surfaceHover,
    '--page-settings-seg-hover-bg': tokens.activeBg,
    '--page-settings-seg-active-bg': mode === 'dark' ? blendHex(tokens.activeBg, tokens.textStrong, 0.88) : spec.surfaceBg,
    '--page-settings-seg-active-border': tokens.borderStrong,
    '--page-settings-switch-off': tokens.borderStrong,
    '--page-settings-tip-border': tokens.borderStrong,
    '--page-settings-footer-btn-bg': tokens.surfaceHover,
    '--page-settings-footer-btn-hover-bg': tokens.activeBg,
    ...Object.fromEntries((['success', 'warning', 'danger'] as const).flatMap((name) => [
      [`--app-border-${name}`, blendHex(tokens[name], tokens.border, 0.4)],
      [`--app-surface-${name}`, blendHex(tokens[name], tokens.surfaceBg, 0.08)],
    ])),
  }
}
