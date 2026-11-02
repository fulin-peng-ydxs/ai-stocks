import { formatNumber, type NumberKind } from '@/utils/numberFormat'
import type { IndicatorField, NumericIndicatorField } from '@/api/stocks'

/** K 线工作区从指标接口消费的完整 MACD 原子输出。 */
export const MACD_INDICATOR_FIELDS = [
  'macd_diff',
  'macd_dea',
  'macd_hist',
  'macd_golden_cross',
  'macd_dead_cross',
] as const satisfies readonly IndicatorField[]

/** 原子指标输出按业务语义展示；参数/阈值的输入精度由指标定义独立维护。 */
const outputKinds: Record<NumericIndicatorField, NumberKind> = {
  ma5: 'price', ma10: 'price', ma20: 'price', ma60: 'price', ma250: 'price',
  hhv60: 'price', hhv120: 'price', hhv240: 'price', hhv480: 'price',
  macd_diff: 'decimal', macd_dea: 'decimal', macd_hist: 'decimal',
  dist_to_high_2y: 'ratio', vol_ma5: 'quantity', vol_ma20: 'quantity', rs_pct: 'decimal',
}
export function formatIndicatorValue(value: unknown, field: IndicatorField): string {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value !== 'number' && typeof value !== 'string') return '—'
  return formatNumber(value, outputKinds[field as NumericIndicatorField] ?? 'decimal')
}
