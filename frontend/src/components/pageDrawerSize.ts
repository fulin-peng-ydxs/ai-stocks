export const PAGE_DRAWER_WIDTHS = {
  sm: '320px',
  md: '360px',
  lg: '440px',
  xl: '560px',
} as const

export type PageDrawerSize = keyof typeof PAGE_DRAWER_WIDTHS

export function isPageDrawerSize(value: unknown): value is PageDrawerSize {
  return typeof value === 'string' && value in PAGE_DRAWER_WIDTHS
}
