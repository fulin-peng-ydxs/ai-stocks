import { computed, shallowRef, watch, type Ref } from 'vue'
import type { Bar } from '@/api/stocks'
import { buildKlineBarQuoteSummary } from '@/components/stock-chart/chartUtils'
import { klineQuoteWindowWidths, type StockQuoteWindow } from '@/components/stock-chart/workspaceOptions'
import type { StockQuoteSupplement } from '@/components/stock-chart/stockQuoteSummary'

/** 行情头部共用图表事件，保持当前周期、光标、测算及字符容量一致。 */
export function useKlineHeaderQuote(bars: Ref<Bar[]>, context: () => unknown) {
  const activeBar = shallowRef<Bar | null>(null)
  const supplement = shallowRef<StockQuoteSupplement | null>(null)
  const quoteWindow = shallowRef<StockQuoteWindow | null>(null)
  watch([bars, context], () => {
    activeBar.value = null
    supplement.value = null
    quoteWindow.value = null
  })
  const summary = computed(() => {
    const bar = activeBar.value ?? quoteWindow.value?.latestBar ?? bars.value.at(-1)
    return bar ? buildKlineBarQuoteSummary(bar, { showTime: true, supplement: supplement.value }) : null
  })
  const widths = computed(() => quoteWindow.value
    ? klineQuoteWindowWidths(quoteWindow.value) : undefined)
  return { activeBar, supplement, quoteWindow, summary, widths }
}
