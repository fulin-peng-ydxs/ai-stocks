export const PAGE_DRAWER_WIDTHS = {
  sm: '320px',
  md: '360px',
  lg: '440px',
  xl: '560px',
  // 资产搜索等需要更宽横向空间的复杂详情，固定宽度不够时使用；窄屏仍有限度下探。
  xxl: 'clamp(640px, 60%, 820px)',
  // 日志、字段差异和长 JSON 在宽屏下需要更多横向空间，页面只消费语义档位。
  wide: 'clamp(560px, 46%, 760px)',
} as const

export type PageDrawerSize = keyof typeof PAGE_DRAWER_WIDTHS

export function isPageDrawerSize(value: unknown): value is PageDrawerSize {
  return typeof value === 'string' && value in PAGE_DRAWER_WIDTHS
}
