import { decimalText, displayDirection, formatNumber, tinyValueHint, type NumericValue } from '@/utils/numberFormat'

export type MarketValueClass = 'up' | 'down' | 'muted' | ''
export interface PercentOptions {
  /** percent=12.34 已经是百分数；ratio=0.1234 是比例。 */
  input: 'percent' | 'ratio'
  forceSign?: boolean
  completion?: boolean
}

/** 所有百分比共享换算和舍入；完成性指标不提前显示 100%。 */
export function formatPercent(value: NumericValue, { input, forceSign = false, completion = false }: PercentOptions): string {
  const normalized = decimalText(value, input === 'ratio' ? 2 : 0)
  if (normalized == null) return '—'
  const text = formatNumber(normalized, 'decimal', { forceSign: completion ? false : forceSign })
  if (completion && !normalized.startsWith('-') && normalized !== '100'
    && normalized.split('.')[0]!.length <= 2 && text === '100.00') return '>99.99%'
  return `${text}%`
}

/** 行情数据已是百分数；收益率等比例字段显式使用 formatReturn。 */
export function formatMarketPercent(value: NumericValue): string {
  return formatPercent(value, { input: 'percent', forceSign: true })
}
export function formatReturn(value: NumericValue): string {
  return formatPercent(value, { input: 'ratio', forceSign: true })
}
export function formatPercentPoints(value: NumericValue, input: 'percent' | 'ratio' = 'percent'): string {
  const normalized = decimalText(value, input === 'ratio' ? 2 : 0)
  return normalized == null ? '—' : `${formatNumber(normalized, 'decimal', { forceSign: true })} 个百分点`
}

/** 与可见数值保持一致；ratio 表示输入仍是比例，金额/价格可指定字段精度。 */
export function marketValueClass(value: NumericValue, options: { input?: 'percent' | 'ratio'; digits?: number } = {}): MarketValueClass {
  const direction = displayDirection(value, options.digits ?? 2, options.input === 'ratio' ? 2 : 0)
  return direction == null ? 'muted' : direction > 0 ? 'up' : direction < 0 ? 'down' : ''
}

export function marketValueTone(value: NumericValue, options: { input?: 'percent' | 'ratio'; digits?: number } = {}): 'up' | 'down' | 'neutral' {
  const tone = marketValueClass(value, options)
  return tone === 'up' || tone === 'down' ? tone : 'neutral'
}

/** 图表悬浮在极小非零值旁提供原精度；轴与常驻主值仍消费固定精度入口。 */
export function formatMarketPercentDetail(value: NumericValue): string {
  const hint = tinyValueHint(value, '%')
  return formatMarketPercent(value) + (hint ? `（${hint}）` : '')
}
export function formatPercentPointsDetail(value: NumericValue): string {
  const hint = tinyValueHint(value, ' 个百分点')
  return formatPercentPoints(value) + (hint ? `（${hint}）` : '')
}
