import { ref, watch, type WatchSource } from 'vue'

/** 两个行情入口共享的分时弹窗状态；切股时统一关闭并让弹窗取消旧请求。 */
export function useStockIntradayDrilldown(stockKey: WatchSource<unknown>) {
  const intradayOpen = ref(false)
  const intradayTradeDate = ref('')
  const intradayRequestKey = ref(0)

  function openIntraday(tradeDate: string): void {
    intradayTradeDate.value = tradeDate
    intradayRequestKey.value += 1
    intradayOpen.value = true
  }

  watch(stockKey, () => {
    intradayOpen.value = false
  })

  return { intradayOpen, intradayTradeDate, intradayRequestKey, openIntraday }
}
