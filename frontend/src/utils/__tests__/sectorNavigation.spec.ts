import { describe, expect, it } from 'vitest'
import { sanitizeSectorSourceQuery } from '../sectorNavigation'

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
    })).toEqual({
      type: 'concept',
      sort: 'pct_5d',
      order: 'asc',
      keyword: '算力',
      page: '3',
      scope: 'watchlist',
      date: '2026-08-11',
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
    })).toEqual({})
  })
})
