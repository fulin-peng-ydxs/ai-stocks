// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import RankedStockWorkbench from '@/components/ranked-stock/RankedStockWorkbench.vue'
import { rankedStockColumns } from '@/components/ranked-stock/types'
import { useStockSet } from '@/stores/stockSet'
import { createDefaultStockAnalysisPreferences } from '@/composables/useStockAnalysisSession'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/screen', component: { template: '<div />' } },
    { path: '/stocks/:code', component: { template: '<div />' } },
  ],
})

describe('RankedStockWorkbench', () => {
  beforeEach(async () => {
    localStorage.clear()
    sessionStorage.clear()
    setActivePinia(createPinia())
    await router.push('/screen')
    await router.isReady()
  })

  it('进入个股详情前登记完整结果集合与返回来源', async () => {
    const wrapper = mount(RankedStockWorkbench, {
      props: {
        registryPageKey: 'screen',
        adjustMode: 'qfq',
        analysisDefaults: createDefaultStockAnalysisPreferences(),
        rows: [
          {
            code: '000001.SZ', name: '平安银行', board: '主板', total_score: 90,
            grade: '观察', sub_scores: {}, is_st: false, score_status: 'ranked', rank: 1,
          },
          {
            code: '600000.SH', name: '浦发银行', board: '主板', total_score: 80,
            grade: '观察', sub_scores: {}, is_st: false, score_status: 'ranked', rank: 2,
          },
        ],
        columns: rankedStockColumns(['rank', 'name', 'score']),
        title: '2026-09-19',
        returnPath: '/screen?profile_ref=opaque',
        collectionLabel: '策略筛选',
      },
      global: {
        plugins: [router],
        stubs: {
          MarketMasterDetailWorkspace: {
            template: '<div><slot name="list" /><slot name="analysis" /></div>',
          },
          RankedStockResultTable: true,
          StockAnalysisPanel: {
            emits: ['open-detail'],
            template: '<button data-testid="open-detail" @click="$emit(\'open-detail\')">详情</button>',
          },
        },
      },
    })

    await wrapper.get('[data-testid="open-detail"]').trigger('click')
    await flushPromises()

    const stockSet = useStockSet()
    expect(stockSet.label).toBe('策略筛选')
    expect(stockSet.returnPath).toBe('/screen?profile_ref=opaque')
    expect(stockSet.items).toEqual([
      { code: '000001.SZ', name: '平安银行' },
      { code: '600000.SH', name: '浦发银行' },
    ])
    expect(router.currentRoute.value.path).toBe('/stocks/000001.SZ')
  })
})
