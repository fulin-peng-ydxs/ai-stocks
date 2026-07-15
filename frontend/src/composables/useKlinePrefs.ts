// 全局 K 线范围偏好：快捷范围选项 + 默认范围，模块级单例 + PG 用户偏好，localStorage 兜底。
// 所有看 K 线的页面（盘感训练 / 个股详情 等）共享同一套范围选项与默认值，抽屉里改一处处处生效。
import { computed } from 'vue'
import { useUserPreference } from './useUserPreference'

const STORAGE_KEY = 'ai-stocks:kline-prefs'
export const ALL_DAYS = 99999 // “全部”范围哨兵值

interface KlinePrefs {
  periods: number[] // 可配置的快捷范围（交易日），升序去重
  includeAll: boolean // 是否提供“全部”选项
  defaultPeriod: number // 新开图表的默认范围
}

const DEFAULTS: KlinePrefs = { periods: [60, 120, 250], includeAll: true, defaultPeriod: 120 }

function sanitize(list: number[]): number[] {
  const arr = Array.from(new Set(list.map(Number).filter((n) => Number.isFinite(n) && n > 0 && n < ALL_DAYS)))
  arr.sort((a, b) => a - b)
  return arr
}

let pref: ReturnType<typeof useUserPreference<KlinePrefs>> | null = null

function preference() {
  if (!pref) {
    pref = useUserPreference<KlinePrefs>({
      scope: 'global',
      prefKey: 'kline-prefs',
      defaults: DEFAULTS,
      localStorageKey: STORAGE_KEY,
    })
  }
  return pref
}

export function useKlinePrefs() {
  const state = preference().value
  const options = computed(() => {
    const opts = state.periods.map((d) => ({ value: d, label: `近 ${d} 日` }))
    if (state.includeAll) opts.push({ value: ALL_DAYS, label: '全部' })
    return opts
  })
  // 归一后的默认范围：默认值被删除/失效时回退到首个可用项
  const validDefault = computed(() => {
    if (state.defaultPeriod === ALL_DAYS) return state.includeAll ? ALL_DAYS : state.periods[0] ?? ALL_DAYS
    if (state.periods.includes(state.defaultPeriod)) return state.defaultPeriod
    return state.periods[0] ?? (state.includeAll ? ALL_DAYS : DEFAULTS.defaultPeriod)
  })
  function setPeriods(list: number[]) {
    const next = sanitize(list)
    if (!next.length) return
    state.periods = next
    // 默认范围若被移出列表（且非“全部”），回落到首个可用项，避免默认下拉显示空白
    if (state.defaultPeriod !== ALL_DAYS && !next.includes(state.defaultPeriod)) {
      state.defaultPeriod = next[0]
    }
  }
  function reset() {
    state.periods = [...DEFAULTS.periods]
    state.includeAll = DEFAULTS.includeAll
    state.defaultPeriod = DEFAULTS.defaultPeriod
  }
  return { prefs: state, options, validDefault, setPeriods, reset }
}
