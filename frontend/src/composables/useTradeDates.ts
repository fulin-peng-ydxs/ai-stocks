// 交易日历共享状态：全站只拉一次 /api/data/trade-dates，缓存为 Set，供日期选择器统一使用
import { ref } from 'vue'
import { getTradeDates } from '@/api/backtest'

// 模块级单例（与 useTheme 同模式）
const tradeDateSet = ref<Set<string>>(new Set())
const dataMin = ref<string | null>(null)
const dataMax = ref<string | null>(null)
const status = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const loadError = ref<unknown>(null)
let loaded = false
let loading: Promise<void> | null = null

function fmtYmd(d: Date): string {
  const m = `${d.getMonth() + 1}`.padStart(2, '0')
  const day = `${d.getDate()}`.padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

async function ensureLoaded(): Promise<void> {
  if (loaded) return
  if (loading) return loading
  status.value = 'loading'
  loadError.value = null
  loading = (async () => {
    try {
      const td = await getTradeDates()
      tradeDateSet.value = new Set(td.dates)
      dataMin.value = td.min
      dataMax.value = td.max
      loaded = true
      status.value = 'ready'
    } catch (error) {
      status.value = 'error'
      loadError.value = error
      /* 加载失败则不限制（fallback：不禁用任何日期）*/
    } finally {
      loading = null
    }
  })()
  return loading
}

// el-date-picker disabled-date：true=禁用。非交易日（含周末/节假日）→ 禁用
function disabledTradeDate(d: Date): boolean {
  if (!tradeDateSet.value.size) return false // 未加载完成前不限制，避免全禁用
  return !tradeDateSet.value.has(fmtYmd(d))
}

// 某交易日的前一个交易日（信号日=买入日的前一交易日）。取不到返回原值。
function prevTradeDate(ymd: string): string {
  if (!tradeDateSet.value.size) return ymd
  let best = ''
  for (const d of tradeDateSet.value) if (d < ymd && d > best) best = d
  return best || ymd
}

export function useTradeDates() {
  return {
    tradeDateSet,
    dataMin,
    dataMax,
    status,
    loadError,
    disabledTradeDate,
    prevTradeDate,
    ensureLoaded,
  }
}
