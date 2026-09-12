import { describe, expect, it } from 'vitest'
import {
  resolveSectorListState,
  sanitizeSectorSourceQuery,
  sectorDetailLocation,
  sectorListLocation,
  sectorReturnLabel,
  trustedSectorReturnPath,
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

  it.each([
    '/limit-ladder?window=20&selected=600001.SH',
    '/stocks?restore=1&page=3',
    '/stocks/600000.SH',
    '/board?date=2026-09-02',
    '/screen?profile_ref=opaque',
  ])('允许返回可信业务列表完整路径：%s', (returnTo) => {
    expect(sectorListLocation({ return_to: returnTo })).toBe(returnTo)
  })

  it('拒绝开放重定向和非来源业务路由', () => {
    expect(sectorListLocation({ return_to: '//evil.example/steal' })).toEqual({
      path: '/sectors',
      query: {},
    })
    expect(trustedSectorReturnPath('/admin?next=/stocks')).toBeUndefined()
  })
})

describe('sectorDetailLocation', () => {
  it('统一编码板块代码并只携带可信来源', () => {
    expect(sectorDetailLocation('概念/AI', '/board?date=2026-09-02')).toEqual({
      path: '/sectors/%E6%A6%82%E5%BF%B5%2FAI',
      query: { return_to: '/board?date=2026-09-02' },
    })
    expect(sectorDetailLocation('881001', 'https://evil.example')).toEqual({
      path: '/sectors/881001',
      query: undefined,
    })
  })
})

describe('sectorReturnLabel', () => {
  it.each([
    ['/limit-ladder?window=20', '返回连板天梯'],
    ['/stocks?page=3', '返回个股查询'],
    ['/stocks/600000.SH', '返回个股详情'],
    ['/board?date=2026-09-02', '返回每日榜单'],
    ['/screen?profile_ref=opaque', '返回策略筛选'],
  ])('按可信来源 %s 展示 %s', (returnTo, label) => {
    expect(sectorReturnLabel({ return_to: returnTo })).toBe(label)
  })

  it('非法或缺失来源使用板块行情兜底文案', () => {
    expect(sectorReturnLabel({ return_to: '/admin' })).toBe('返回板块行情')
    expect(sectorReturnLabel({})).toBe('返回板块行情')
  })
})
