export const DEFAULT_MARKET_BENCHMARK_CODE = '000905.SH'

/** 系统市场指数单一注册表；板块、个股和回测的选项与持久化校验统一消费。 */
export const MARKET_BENCHMARKS = [
  { label: '中证 500', value: '000905.SH' },
  { label: '沪深 300', value: '000300.SH' },
  { label: '上证指数', value: '000001.SH' },
  { label: '科创 50', value: '000688.SH' },
  { label: '深证成指', value: '399001.SZ' },
  { label: '创业板指', value: '399006.SZ' },
] as const

export const MARKET_BENCHMARK_OPTIONS = [
  { label: '不对比指数', value: '' },
  ...MARKET_BENCHMARKS,
]

const MARKET_BENCHMARK_CODES = new Set<string>(MARKET_BENCHMARKS.map((item) => item.value))

export function isMarketBenchmarkCode(value: unknown): value is string {
  return typeof value === 'string' && MARKET_BENCHMARK_CODES.has(value)
}

/** 持久化偏好允许显式不对比；未知旧值稳定回落到系统默认基准。 */
export function normalizeMarketBenchmarkCode(value: unknown): string {
  if (value === '') return ''
  return isMarketBenchmarkCode(value) ? value : DEFAULT_MARKET_BENCHMARK_CODE
}
