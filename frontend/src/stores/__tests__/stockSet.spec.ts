// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useStockSet, type StockListState } from '@/stores/stockSet'

const LIST_STATE: StockListState = {
  mode: 'group',
  q: '',
  board: '',
  excludeSt: true,
  tradeDate: '2026-01-05',
  sortBy: 'pct_chg',
  sortOrder: 'asc',
  page: 1,
  size: 20,
  activeGid: 'gid-1',
  groupPage: 1,
  groupSize: 20,
  groupQ: '',
  groupSortBy: 'add_date',
  groupSortOrder: 'asc',
}

describe('stockSet group context cleanup', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('clears persisted group collection without dropping list restore state', () => {
    const stockSet = useStockSet()
    stockSet.setListState(LIST_STATE)
    stockSet.setSet(
      'group',
      [{ code: '000001.SZ', name: '平安银行' }],
      '自选分组',
      'gid-1',
      {
        query: { kind: 'group', groupId: 'gid-1', params: { page: 1, size: 20 } },
        total: 1,
        loadedPages: [1],
        pageSize: 20,
      },
    )

    expect(stockSet.clearGroupContext()).toBe(true)
    expect(stockSet.source).toBe('')
    expect(stockSet.returnPath).toBe('')
    expect(stockSet.groupId).toBe('')
    expect(stockSet.items).toEqual([])
    expect(stockSet.query).toBeNull()
    expect(stockSet.listState?.activeGid).toBe('gid-1')

    const persisted = JSON.parse(localStorage.getItem('ai-stocks:stockSet') || '{}')
    expect(persisted.source).toBe('')
    expect(persisted.query).toBeNull()
    expect(persisted.listState.activeGid).toBe('gid-1')
  })

  it('does not clear a normal stock list collection', () => {
    const stockSet = useStockSet()
    stockSet.setSet(
      'list',
      [{ code: '000001.SZ', name: '平安银行' }],
      '查询结果',
      '',
      {
        query: { kind: 'stocks', params: { q: '000001', page: 1, size: 20 } },
        total: 1,
        loadedPages: [1],
        pageSize: 20,
      },
    )

    expect(stockSet.clearGroupContext()).toBe(false)
    expect(stockSet.source).toBe('list')
    expect(stockSet.items).toHaveLength(1)
    expect(stockSet.query?.kind).toBe('stocks')
    expect(stockSet.returnPath).toBe('/stocks?restore=1')
  })

  it('persists a custom collection return path', () => {
    const stockSet = useStockSet()
    stockSet.setSet(
      'list',
      [{ code: '000001.SZ', name: '平安银行' }],
      '每日榜单',
      '',
      { returnPath: '/board' },
    )

    expect(stockSet.returnPath).toBe('/board')
    expect(JSON.parse(localStorage.getItem('ai-stocks:stockSet') || '{}').returnPath).toBe('/board')
  })
})
