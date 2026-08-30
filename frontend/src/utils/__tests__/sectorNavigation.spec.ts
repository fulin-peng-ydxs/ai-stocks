import { describe, expect, it } from 'vitest'
import {
  resolveSectorListState,
  sanitizeSectorSourceQuery,
  sectorListLocation,
} from '../sectorNavigation'

describe('sanitizeSectorSourceQuery', () => {
  it('保留板块列表可恢复的合法来源状态', () => {
    expect(sanitizeSectorSourceQuery({
      type: 'concept',
      sort: 'pct_5d',
      order: 'asc',
      keyword: '  算力  ',
      page: '3',
      scope: 'watchlist',
      date: '2026-08-11',
      return_to: '/limit-ladder?window=31&selected=600001.SH',
    })).toEqual({
      type: 'concept',
      sort: 'pct_5d',
      order: 'asc',
      keyword: '算力',
      page: '3',
      scope: 'watchlist',
      date: '2026-08-11',
      return_to: '/limit-ladder?window=31&selected=600001.SH',
    })
  })

  it('逐字段丢弃非法来源参数', () => {
    expect(sanitizeSectorSourceQuery({
      type: 'all',
      sort: 'name',
      order: 'sideways',
      page: '0',
      scope: 'mine',
      date: '2026/08/11',
      extra: 'ignored',
      return_to: 'https://evil.example/steal',
    })).toEqual({})
  })
})

describe('resolveSectorListState', () => {
  it('URL 来源态覆盖保存偏好，业务偏好继续控制图表默认项', () => {
    expect(resolveSectorListState(
      { type: 'concept', scope: 'watchlist', keyword: '算力', page: '3' },
      {
        defaultType: 'industry',
        defaultScope: 'all',
        defaultChartMode: 'kline',
        benchmarkCode: '000300.SH',
      },
      true,
    )).toMatchObject({
      boardType: 'concept',
      listScope: 'watchlist',
      chartMode: 'kline',
      benchmarkCode: '000300.SH',
      keyword: '算力',
      page: 3,
    })
  })

  it('非法偏好回落默认，无自选权限时强制全市场', () => {
    expect(resolveSectorListState(
      { scope: 'watchlist' },
      {
        defaultType: 'invalid',
        defaultScope: 'watchlist',
        defaultChartMode: 'invalid',
        benchmarkCode: 'invalid',
      },
      false,
    )).toMatchObject({
      boardType: '',
      listScope: 'all',
      chartMode: 'compare',
      benchmarkCode: '000905.SH',
      keyword: '',
      page: 1,
    })
  })

  it('新增市场指数可直接恢复为板块对比基准', () => {
    expect(resolveSectorListState(
      {},
      { benchmarkCode: '399006.SZ' },
      true,
    ).benchmarkCode).toBe('399006.SZ')
  })
})

describe('sectorListLocation', () => {
  it('详情显式返回仅携带合法来源参数', () => {
    expect(sectorListLocation({
      type: 'industry',
      sort: 'pct_5d',
      page: '2',
      injected: '/admin',
    })).toEqual({
      path: '/sectors',
      query: { type: 'industry', sort: 'pct_5d', page: '2' },
    })
  })

  it('无合法来源参数时返回默认列表', () => {
    expect(sectorListLocation({ sort: 'name', page: '-1' })).toEqual({
      path: '/sectors',
      query: {},
    })
  })

  it('仅允许返回连板天梯的内部完整路径，拒绝开放重定向', () => {
    expect(sectorListLocation({
      return_to: '/limit-ladder?window=20&boards=main,gem&selected=600001.SH',
    })).toBe('/limit-ladder?window=20&boards=main,gem&selected=600001.SH')
    expect(sectorListLocation({ return_to: '//evil.example/steal' })).toEqual({
      path: '/sectors',
      query: {},
    })
  })
})
