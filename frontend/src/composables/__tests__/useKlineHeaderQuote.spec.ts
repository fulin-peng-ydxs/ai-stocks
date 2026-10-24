import { describe, expect, it } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import type { Bar } from '@/api/stocks'
import { useKlineHeaderQuote } from '../useKlineHeaderQuote'

const bar = (date: string, close: number): Bar => ({
  date, open: close, high: close + 1, low: close - 1, close,
  pre_close: close - 0.5, volume: 100, amount: 1000, turnover_rate: null,
})

describe('板块头部行情联动', () => {
  it('光标离开恢复当前周期最新值，历史光标不重算字符容量', async () => {
    const scope = effectScope()
    const bars = ref([bar('2026-10-22', 12), bar('2026-10-23', 14)])
    const quote = scope.run(() => useKlineHeaderQuote(bars, () => 'industry'))!
    quote.quoteWindow.value = {
      latestBar: bars.value[1]!, bars: bars.value, supplements: [null, null],
    }
    const widths = quote.widths.value
    quote.activeBar.value = bars.value[0]!
    expect(quote.summary.value?.hero.value).toBe('12.00')
    expect(quote.widths.value).toBe(widths)
    quote.activeBar.value = null
    expect(quote.summary.value?.hero.value).toBe('14.00')
    // 周期聚合后的最新值来自图表，不能回退到日线列表末值。
    quote.quoteWindow.value = { latestBar: bar('2026-10-23', 18), bars: [], supplements: [] }
    expect(quote.summary.value?.hero.value).toBe('18.00')
    bars.value = []
    await nextTick()
    expect(quote.summary.value).toBeNull()
    scope.stop()
  })

  it('切换板块、模式或周期时清理旧光标、测算和容量', async () => {
    const scope = effectScope()
    const context = ref('A:day')
    const bars = ref([bar('2026-10-23', 14)])
    const quote = scope.run(() => useKlineHeaderQuote(bars, () => context.value))!
    quote.activeBar.value = bar('2026-10-01', 11)
    quote.supplement.value = { label: '截止涨幅', value: '+3.00%', tone: 'up' }
    quote.quoteWindow.value = { latestBar: bars.value[0]!, bars: bars.value, supplements: [] }
    expect(quote.summary.value?.supplement?.value).toBe('+3.00%')
    context.value = 'B:week'
    await nextTick()
    expect(quote.activeBar.value).toBeNull()
    expect(quote.quoteWindow.value).toBeNull()
    expect(quote.summary.value?.supplement).toBeNull()
    expect(quote.widths.value).toBeUndefined()
    scope.stop()
  })
})
