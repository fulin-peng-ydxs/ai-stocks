import { describe, expect, it } from 'vitest'
import { DEFAULT_LIMIT_LADDER_FILTERS, filtersFromRouteQuery } from '@/api/limitLadder'
import {
  DEFAULT_LIMIT_LADDER_PREFERENCE,
  filtersFromLimitLadderPreference,
  normalizeLimitLadderPreference,
} from '@/views/limit-ladder/preferences'

describe('limit ladder preferences', () => {
  it('兼容无版本旧值并规范化可识别字段', () => {
    expect(normalizeLimitLadderPreference({
      window: 20,
      ignoreSt: false,
      boards: ['main', 'gem'],
      showAnalysisPanel: true,
    })).toEqual({
      ...DEFAULT_LIMIT_LADDER_PREFERENCE,
      schemaVersion: 1,
      window: 20,
      ignoreSt: false,
      boards: ['main', 'gem'],
      showAnalysisPanel: true,
    })
  })

  it('补齐走势图和层内排序默认值，并规范化非法值', () => {
    expect(normalizeLimitLadderPreference({
      schemaVersion: 1,
      cardSort: 'industry',
      cardSortOrder: 'asc',
      defaultChartMode: 'kline',
      compareRange: 120,
      benchmarkCode: '000300.SH',
      compareMetrics: ['cum', 'roll_20d'],
      defaultCompareMetric: 'roll_20d',
      adjustMode: 'hfq',
    })).toMatchObject({
      cardSort: 'industry',
      cardSortOrder: 'asc',
      defaultChartMode: 'kline',
      compareRange: 120,
      benchmarkCode: '000300.SH',
      compareMetrics: ['cum', 'roll_20d'],
      defaultCompareMetric: 'roll_20d',
      adjustMode: 'hfq',
    })
    expect(normalizeLimitLadderPreference({
      cardSort: 'unknown',
      cardSortOrder: 'unknown',
      benchmarkCode: 'unknown',
      compareMetrics: [],
    })).toMatchObject({
      cardSort: 'limitUps',
      cardSortOrder: 'desc',
      benchmarkCode: '000905.SH',
      compareMetrics: DEFAULT_LIMIT_LADDER_PREFERENCE.compareMetrics,
      defaultCompareMetric: 'cum',
    })
    expect(normalizeLimitLadderPreference({
      cardSort: 'industry',
    })).toMatchObject({
      cardSort: 'industry',
      cardSortOrder: 'asc',
    })
  })

  it('未知版本、非法窗口和未知板块安全回退系统默认', () => {
    expect(normalizeLimitLadderPreference({
      schemaVersion: 2,
      window: 10,
      ignoreSt: false,
      boards: ['main'],
      showAnalysisPanel: true,
    })).toEqual(DEFAULT_LIMIT_LADDER_PREFERENCE)

    expect(normalizeLimitLadderPreference({
      schemaVersion: 1,
      window: 12,
      ignoreSt: 'false',
      boards: ['main', 'unknown'],
      showAnalysisPanel: 'true',
    })).toEqual(DEFAULT_LIMIT_LADDER_PREFERENCE)
  })

  it('个人默认覆盖系统默认，显式 URL 再覆盖个人默认', () => {
    const preference = normalizeLimitLadderPreference({
      schemaVersion: 1,
      window: 20,
      ignoreSt: false,
      boards: ['star'],
      showAnalysisPanel: true,
    })
    const preferredFilters = filtersFromLimitLadderPreference(preference)
    expect(filtersFromRouteQuery({}, preferredFilters)).toEqual({
      ...DEFAULT_LIMIT_LADDER_FILTERS,
      window: 20,
      ignoreSt: false,
      boards: ['star'],
    })
    expect(filtersFromRouteQuery({
      window: '60',
      boards: 'main,gem',
      ignore_st: '1',
    }, preferredFilters)).toEqual({
      ...DEFAULT_LIMIT_LADDER_FILTERS,
      window: 60,
      ignoreSt: true,
      boards: ['main', 'gem'],
    })
  })
})
