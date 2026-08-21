import { onBeforeUnmount } from 'vue'

export interface DebouncedQuery {
  /** 关键字输入：防抖后触发（默认 300ms）。 */
  schedule: () => void
  /** 回车 / 清空 / 离散控件改选：取消排队并立即触发。 */
  flush: () => void
  /** 卸载时清理定时器，避免路由切换后仍触发查询。 */
  cancel: () => void
}

/**
 * 统一"用户筛选/查询动作 → 触发查询"的防抖编排，替代各页面手写 setTimeout。
 * resetAndReload 由调用方提供，形如 `() => { page.value = 1; void load() }`。
 * schedule 用于关键字输入（防抖）；flush 用于回车/清空/下拉/日期等离散动作（立即）。
 */
export function useDebouncedQuery(resetAndReload: () => void, debounceMs = 300): DebouncedQuery {
  let timer: ReturnType<typeof setTimeout> | null = null

  const cancel = () => {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  const flush = () => {
    cancel()
    resetAndReload()
  }

  const schedule = () => {
    cancel()
    timer = setTimeout(() => {
      timer = null
      resetAndReload()
    }, debounceMs)
  }

  onBeforeUnmount(cancel)

  return { schedule, flush, cancel }
}
