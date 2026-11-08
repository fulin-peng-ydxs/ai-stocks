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
): LoginSurfaceSpec {
  return {
    pageBg,
    sidebarBg,
    cardBg,
    cardAlpha,
    surfaceBg: blendHex(cardBg, pageBg, cardAlpha),
  }
}

/**
 * 明暗模式的固定基础表面。
 * 预设只能覆盖强调色和形态，不能改变主画布、边栏、卡片与文字的中性底色；边界消费预设的统一边框角色。
 */
export const THEME_SURFACE_SPECS: Record<ThemeMode, LoginSurfaceSpec> = {
  // 导航使用等通道近白色，只比纯白内容区稍暗，保留轻微层次。
  light: surface('#ffffff', '#fdfdfd', '#ffffff', 1),
  dark: surface('#171717', '#1f1f1f', '#171717', 1),
}

export function getLoginSurfaceSpec(mode: ThemeMode): LoginSurfaceSpec {
  return THEME_SURFACE_SPECS[mode]
}

/** 控件保留完整边界，表面和分隔线向内容面收敛；暗色保留更高轮廓强度。 */
export function themeBorderVariables(tokens: StyleTokenConfig, mode: ThemeMode): Record<string, string> {
  const subtle = blendHex(tokens.border, tokens.surfaceBg, mode === 'dark' ? 0.85 : 0.6)
  const divider = blendHex(tokens.border, tokens.surfaceBg, mode === 'dark' ? 0.7 : 0.42)
  return {
    '--app-border-divider': divider,
    '--app-border-subtle': subtle,
    '--app-border-default': tokens.border,
    '--app-border-strong': tokens.borderStrong,
    '--app-border-selected': tokens.primary,
    '--el-border-color': tokens.border,
    '--el-border-color-light': subtle,
    '--el-border-color-lighter': divider,
    '--el-border-color-extra-light': blendHex(tokens.border, tokens.surfaceBg, mode === 'dark' ? 0.6 : 0.34),
    '--el-border-color-dark': tokens.borderStrong,
    '--el-border-color-darker': tokens.borderStrong,
    '--el-disabled-border-color': tokens.border,
    ...Object.fromEntries((['success', 'warning', 'danger'] as const).map((name) => [
      `--app-border-${name}`, blendHex(tokens[name], tokens.border, 0.4),
    ])),
  }
}

/** 中性分段是参数选择；轨道、选中和悬浮共享配方，不借用分组边框或命令投影。 */
export function themeSelectionVariables(tokens: StyleTokenConfig, mode: ThemeMode): Record<string, string> {
  const borders = themeBorderVariables(tokens, mode)
  const track = mode === 'dark'
    ? tokens.surfaceHover : blendHex(tokens.surfaceHover, tokens.surfaceBg, 0.75)
  return {
    '--page-settings-seg-bg': track,
    '--page-settings-seg-border': borders['--app-border-divider'],
    '--page-settings-seg-hover-bg': blendHex(tokens.textStrong, track, 0.04),
    '--page-settings-seg-active-bg': mode === 'dark'
      ? blendHex(tokens.activeBg, tokens.textStrong, 0.88) : tokens.surfaceBg,
    '--page-settings-seg-active-border': borders['--app-border-subtle'],
  }
}
