import type { IndicatorField } from '@/api/stocks'

/** K 线工作区从指标接口消费的完整 MACD 原子输出。 */
export const MACD_INDICATOR_FIELDS = [
  'macd_diff',
  'macd_dea',
  'macd_hist',
  'macd_golden_cross',
  'macd_dead_cross',
] as const satisfies readonly IndicatorField[]
