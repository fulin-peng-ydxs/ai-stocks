import type { LayoutPresetKey, ThemeMode } from './schema'

export interface LoginSurfaceSpec {
  /** 登录页右侧交互区的基础画布色，同时也是工作台 pageBg。 */
  pageBg: string
  /** 登录卡片的原始基色；登录页可用透明度和模糊保留玻璃材质。 */
  cardBg: string
  /** 登录卡片在 pageBg 上叠加时使用的透明度。 */
  cardAlpha: number
  /** 登录卡片叠加后的肉眼可见色，同时也是工作台 surfaceBg。 */
  surfaceBg: string
}

function parseHex(hex: string): [number, number, number] {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return [NaN, NaN, NaN]
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function toHex(channels: number[]): string {
  return `#${channels
    .map((value) => Math.round(value).toString(16).padStart(2, '0'))
    .join('')}`
}

export function blendHex(foreground: string, background: string, alpha: number): string {
  const fg = parseHex(foreground)
  const bg = parseHex(background)
  return toHex(fg.map((value, index) => value * alpha + bg[index] * (1 - alpha)))
}

export function rgbaFromHex(hex: string, alpha: number): string {
  const [r, g, b] = parseHex(hex)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function surface(pageBg: string, cardBg: string, cardAlpha: number): LoginSurfaceSpec {
  return {
    pageBg,
    cardBg,
    cardAlpha,
    surfaceBg: blendHex(cardBg, pageBg, cardAlpha),
  }
}

export const THEME_SURFACE_SPECS: Record<LayoutPresetKey, Record<ThemeMode, LoginSurfaceSpec>> = {
  daylight: {
    light: surface('#f1f4f9', '#fdfefe', 0.92),
    dark: surface('#171b24', '#202632', 0.92),
  },
  nocturne: {
    light: surface('#e8eef1', '#f8fafb', 0.92),
    dark: surface('#071721', '#0d222e', 0.94),
  },
  balanced: {
    light: surface('#edf1f4', '#fafcfd', 0.86),
    dark: surface('#07131d', '#0a1b27', 0.9),
  },
}

export function getLoginSurfaceSpec(
  preset: LayoutPresetKey,
  mode: ThemeMode,
): LoginSurfaceSpec {
  return THEME_SURFACE_SPECS[preset][mode]
}
