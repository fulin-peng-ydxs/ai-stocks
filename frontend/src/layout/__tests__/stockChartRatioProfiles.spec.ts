import { describe, expect, it } from 'vitest'
import {
  closestStockChartRatioProfile,
  normalizeStockChartRatioProfiles,
  upsertStockChartRatioProfile,
} from '@/layout/stockChartRatioProfiles'

describe('stockChartRatioProfiles', () => {
  it('按工作区宽高选择 15% 范围内距离最近的图表比例档案', () => {
    const profiles = [
      { width: 1200, height: 720, ratios: [0.6, 0.2, 0.2] },
      { width: 1440, height: 800, ratios: [0.5, 0.3, 0.2] },
    ]

    expect(closestStockChartRatioProfile(profiles, { width: 1400, height: 780 }, 3)?.ratios)
      .toEqual([0.5, 0.3, 0.2])
    expect(closestStockChartRatioProfile(profiles, { width: 900, height: 600 }, 3))
      .toBeUndefined()
  })

  it('5% 内重复保存更新原档案，明显不同尺寸新增档案', () => {
    const original = [{ width: 1200, height: 720, ratios: [0.6, 0.2, 0.2] }]
    const merged = upsertStockChartRatioProfile(original, {
      width: 1240,
      height: 700,
      ratios: [0.5, 0.25, 0.25],
    })
    expect(merged).toEqual([{ width: 1240, height: 700, ratios: [0.5, 0.25, 0.25] }])

    expect(upsertStockChartRatioProfile(merged, {
      width: 1600,
      height: 900,
      ratios: [0.55, 0.25, 0.2],
    })).toHaveLength(2)
  })

  it('归一化时过滤非法维度、错误组合长度和非 100% 比例', () => {
    expect(normalizeStockChartRatioProfiles([
      { width: 1200, height: 720, ratios: [0.6, 0.2, 0.2] },
      { width: 0, height: 720, ratios: [0.6, 0.2, 0.2] },
      { width: 1400, height: 800, ratios: [0.7, 0.3] },
      { width: 1600, height: 900, ratios: [0.5, 0.2, 0.2] },
    ], 3)).toEqual([{ width: 1200, height: 720, ratios: [0.6, 0.2, 0.2] }])
  })
})
