// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useLimitLadderSessionStore } from '@/stores/limitLadderSession'

describe('limitLadderSession store', () => {
  beforeEach(() => {
    sessionStorage.clear()
    setActivePinia(createPinia())
  })

  it('按当前 Tab 保存并一次性消费连板天梯返回现场', () => {
    const store = useLimitLadderSessionStore()
    store.saveReturnState({
      tradeDate: '2026-09-11',
      filters: {
        window: 20,
        boards: ['main', 'gem'],
        ignoreSt: false,
        oneWordOnly: false,
        keyword: '',
        hotspotType: null,
        hotspotKey: null,
      },
      cardSort: 'industry',
      cardSortOrder: 'desc',
      selectedCode: '600000.SH',
      anchorCode: '600000.SH',
    })

    expect(store.consumeReturnState()).toMatchObject({
      tradeDate: '2026-09-11',
      cardSort: 'industry',
      cardSortOrder: 'desc',
      selectedCode: '600000.SH',
    })
    expect(store.consumeReturnState()).toBeNull()
  })
})
