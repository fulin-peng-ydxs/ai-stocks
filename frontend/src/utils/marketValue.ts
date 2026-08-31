export type MarketValueClass = 'up' | 'down' | 'muted' | ''

/** Format a percentage with the A-share sign convention and a stable empty value. */
export function formatMarketPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

/** Map a signed market value to the global financial up/down semantic classes. */
export function marketValueClass(value: number | null | undefined): MarketValueClass {
  if (value == null || !Number.isFinite(value)) return 'muted'
  return value > 0 ? 'up' : value < 0 ? 'down' : ''
}
