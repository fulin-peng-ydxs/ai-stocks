// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSectorsSessionStore } from '@/stores/sectorsSession'

describe('sectorsSession store', () => {
  beforeEach(() => {
    sessionStorage.clear()
    setActivePinia(createPinia())
  })

  it('按当前 Tab 保存并一次性消费板块列表返回现场', () => {
    const store = useSectorsSessionStore()
    store.saveListReturnState({
      tradeDate: '2026-09-11',
      boardType: 'concept',
      listScope: 'watchlist',
      keyword: '算力',
      sortBy: 'pct_5d',
      sortOrder: 'asc',
      page: 3,
      size: 50,
      chartMode: 'compare',
      benchmarkCode: '000300.SH',
      compareMetric: 'roll_5d',
      compareWindow: 120,
      rangeDays: 60,
      analysisPanelVisible: true,
      activeCode: 'C001',
      pinnedCodes: ['C001'],
      queueCodes: ['C001', 'C002'],
      queueRows: [],
    })

    expect(store.consumeListReturnState()).toMatchObject({
      boardType: 'concept',
      sortBy: 'pct_5d',
      activeCode: 'C001',
      queueCodes: ['C001', 'C002'],
    })
    expect(store.consumeListReturnState()).toBeNull()
  })

  it('详情返回现场按板块代码匹配，避免恢复到其他缓存详情实例', () => {
    const store = useSectorsSessionStore()
    store.saveDetailReturnState({
      boardCode: 'C001',
      tradeDate: '2026-09-11',
      memberKeyword: '600000',
      memberPage: 2,
      memberSize: 30,
      memberSortBy: 'price',
      memberSortOrder: 'asc',
      viewDays: 120,
      returnPath: '/limit-ladder?restore=1',
    })

    expect(store.consumeDetailReturnState('C002')).toBeNull()
    expect(store.consumeDetailReturnState('C001')).toMatchObject({
      memberKeyword: '600000',
      memberSortBy: 'price',
      returnPath: '/limit-ladder?restore=1',
    })
    expect(store.consumeDetailReturnState('C001')).toBeNull()
  })
})
