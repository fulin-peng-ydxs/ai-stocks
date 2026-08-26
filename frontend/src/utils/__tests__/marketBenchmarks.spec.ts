import { describe, expect, it } from 'vitest'
import {
  DEFAULT_MARKET_BENCHMARK_CODE,
  MARKET_BENCHMARK_OPTIONS,
  MARKET_BENCHMARKS,
  isMarketBenchmarkCode,
  normalizeMarketBenchmarkCode,
} from '@/utils/marketBenchmarks'

describe('marketBenchmarks', () => {
  it('统一注册系统支持的六个指数及不对比选项', () => {
    expect(MARKET_BENCHMARKS).toEqual([
      { label: '中证 500', value: '000905.SH' },
      { label: '沪深 300', value: '000300.SH' },
      { label: '上证指数', value: '000001.SH' },
      { label: '科创 50', value: '000688.SH' },
      { label: '深证成指', value: '399001.SZ' },
      { label: '创业板指', value: '399006.SZ' },
    ])
    expect(MARKET_BENCHMARK_OPTIONS[0]).toEqual({ label: '不对比指数', value: '' })
  })

  it('新指数可用于偏好恢复，非法值回落到默认基准', () => {
    for (const code of ['000001.SH', '000688.SH', '399001.SZ', '399006.SZ']) {
      expect(isMarketBenchmarkCode(code)).toBe(true)
      expect(normalizeMarketBenchmarkCode(code)).toBe(code)
    }
    expect(normalizeMarketBenchmarkCode('')).toBe('')
    expect(normalizeMarketBenchmarkCode('invalid')).toBe(DEFAULT_MARKET_BENCHMARK_CODE)
  })
})
