import { ref } from 'vue'
import {
  getTradeDisciplineSummary,
  type CheckinSummary,
} from '@/api/tradeDiscipline'
import { getErrorMessage } from '@/utils/error'

export type TradeDisciplineSummaryStatus = 'idle' | 'loading' | 'ready' | 'error'
export type TradeDisciplineChangeSource = 'quick' | 'workbench'

export interface TradeDisciplineChange {
  ruleId: string
  tradeDate: string
  source: TradeDisciplineChangeSource
}

// 用户中心与已挂载工作台共享同一份最新日摘要，并用变更序号完成跨入口刷新。
// 历史日期仍由工作台自行查询，避免不同日期的数据互相覆盖。
const summary = ref<CheckinSummary | null>(null)
const status = ref<TradeDisciplineSummaryStatus>('idle')
const errorMessage = ref('')
const changeVersion = ref(0)
const latestChange = ref<TradeDisciplineChange | null>(null)
let requestSeq = 0

async function refreshSummary(tradeDate: string): Promise<void> {
  if (!tradeDate) {
    resetSummary()
    return
  }
  const seq = ++requestSeq
  status.value = 'loading'
  errorMessage.value = ''
  try {
    const result = await getTradeDisciplineSummary(tradeDate)
    if (seq !== requestSeq) return
    summary.value = result
    status.value = 'ready'
  } catch (error) {
    if (seq !== requestSeq) return
    summary.value = null
    status.value = 'error'
    errorMessage.value = getErrorMessage(error, '今日交易纪律加载失败')
  }
}

function resetSummary(): void {
  requestSeq += 1
  summary.value = null
  status.value = 'idle'
  errorMessage.value = ''
}

function notifyTradeDisciplineChanged(change: TradeDisciplineChange): void {
  latestChange.value = change
  changeVersion.value += 1
}

export function useTradeDisciplineSummary() {
  return {
    summary,
    status,
    errorMessage,
    changeVersion,
    latestChange,
    refreshSummary,
    resetSummary,
    notifyTradeDisciplineChanged,
  }
}

export function resetTradeDisciplineSummaryForTests(): void {
  resetSummary()
  latestChange.value = null
  changeVersion.value = 0
}
