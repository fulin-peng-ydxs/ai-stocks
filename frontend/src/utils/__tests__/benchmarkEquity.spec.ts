// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { fetchBenchmarkEquity, normalizeBenchmarkEquity } from '@/utils/benchmarkEquity'
import { getSectorBenchmarkBars } from '@/api/sectors'

vi.mock('@/api/sectors', () => ({
  getSectorBenchmarkBars: vi.fn(),
}))

const mockedGet = vi.mocked(getSectorBenchmarkBars)

describe('normalizeBenchmarkEquity', () => {
  const bars = (closes: number[]) => closes.map((close) => ({
    trade_date: '2026-08-01', open: close, high: close, low: close, close, volume: 1, amount: 1,
  }))

  it('按首日收盘归一成资金净值（initCap × close/首日）', () => {
    expect(normalizeBenchmarkEquity(bars([100, 102, 101]), 1_000_000)).toEqual([1_000_000, 1_020_000, 1_010_000])
  })

  it('首日无效收盘：跳过取首个有效收盘为基准，无效日置 null', () => {
    const bad = bars([0, 100, 102])
    expect(normalizeBenchmarkEquity(bad, 1_000_000)).toEqual([null, 1_000_000, 1_020_000])
  })

  it('全部无效收盘 → 全 null', () => {
    const bad = bars([0, 0])
    expect(normalizeBenchmarkEquity(bad, 1_000_000)).toEqual([null, null])
  })
})

describe('fetchBenchmarkEquity', () => {
  it('空 code → 返回 null，不发请求', async () => {
    expect(await fetchBenchmarkEquity('', '2026-01-01', '2026-02-01', 1_000_000)).toBeNull()
    expect(mockedGet).not.toHaveBeenCalled()
  })

  it('接口返回行情 → 归一成净值曲线', async () => {
    mockedGet.mockResolvedValue({
      index_code: '000300.SH', name: '沪深 300', start: '2026-01-01', end: '2026-02-01',
      list: [
        { trade_date: '2026-01-02', open: 3000, high: 3000, low: 3000, close: 3000, volume: 1, amount: 1 },
        { trade_date: '2026-01-05', open: 3030, high: 3030, low: 3030, close: 3030, volume: 1, amount: 1 },
      ],
    })
    const res = await fetchBenchmarkEquity('000300.SH', '2026-01-01', '2026-02-01', 1_000_000)
    expect(mockedGet).toHaveBeenCalledWith('000300.SH', '2026-01-01', '2026-02-01')
    expect(res).toEqual({ code: '000300.SH', name: '沪深 300', equity: [1_000_000, 1_010_000] })
  })

  it('空 list / 接口异常 → null（回退默认基准线）', async () => {
    mockedGet.mockResolvedValue({ index_code: '000300.SH', name: '沪深 300', start: '', end: '', list: [] })
    expect(await fetchBenchmarkEquity('000300.SH', '2026-01-01', '2026-02-01', 1_000_000)).toBeNull()

    mockedGet.mockRejectedValue(new Error('网络错误'))
    expect(await fetchBenchmarkEquity('000300.SH', '2026-01-01', '2026-02-01', 1_000_000)).toBeNull()
  })
})
