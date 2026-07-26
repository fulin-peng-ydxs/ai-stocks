import type { StyleTokenConfig, ThemeMode } from './schema'

export const STYLE_COLOR_TOKEN_KEYS = [
  'primary',
  'success',
  'warning',
  'danger',
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
 * 预设只能覆盖强调色和形态，不能改变主画布、边栏、卡片、文字与边界的中性底色。
 */
export const THEME_SURFACE_SPECS: Record<ThemeMode, LoginSurfaceSpec> = {
  light: surface('#ffffff', '#fcfcfc', '#ffffff', 1),
  dark: surface('#171717', '#1f1f1f', '#1b1b1b', 1),
}

export function getLoginSurfaceSpec(mode: ThemeMode): LoginSurfaceSpec {
  return THEME_SURFACE_SPECS[mode]
}
