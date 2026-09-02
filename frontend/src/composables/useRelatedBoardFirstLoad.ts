import { onBeforeUnmount } from 'vue'
import type { StockRelatedBoards } from '@/types/relatedBoards'

interface RelatedBoardRow {
  code?: string
  related_boards?: StockRelatedBoards | null
}

interface FirstLoadPollingOptions {
  intervalMs?: number
  timeoutMs?: number
}

/** 用股票和业务日期标识一次读取上下文，切页/切日期后必须重新计算等待时限。 */
export function relatedBoardFirstLoadContext<T extends RelatedBoardRow>(
  rows: T[],
  businessDate: string | ((row: T) => string | null | undefined),
): string {
  return rows
    .map((row) => {
      const rowDate = typeof businessDate === 'function' ? businessDate(row) : businessDate
      return `${row.code ?? ''}@${rowDate ?? ''}`
    })
    .sort()
    .join('|')
}

/**
 * 统一观察四类走势摘要消费页返回的首次计算状态；只轮询调用方已有业务读取接口，
 * 避免普通业务用户依赖 system-only 任务详情权限，也不让各页面复制轮询生命周期。
 */
export function useRelatedBoardFirstLoad(
  refresh: () => unknown | Promise<unknown>,
  options: FirstLoadPollingOptions = {},
) {
  const intervalMs = options.intervalMs ?? 1500
  const timeoutMs = options.timeoutMs ?? 120_000
  let timer: number | undefined
  let polling = false
  let disposed = false
  let pending = false
  let startedAt = 0
  let activeContext = ''

  function schedule(): void {
    if (disposed || timer !== undefined || polling || !pending) return
    timer = window.setTimeout(() => {
      timer = undefined
      void poll()
    }, intervalMs)
  }

  async function poll(): Promise<void> {
    if (disposed || polling || !pending) return
    polling = true
    try {
      await refresh()
    } finally {
      polling = false
      if (startedAt && Date.now() - startedAt >= timeoutMs) pending = false
      schedule()
    }
  }

  function observe(rows: RelatedBoardRow[], context = ''): void {
    if (context && context !== activeContext) {
      activeContext = context
      // 轮询刷新可能因行情变化带回另一页股票，不能因此无限延长本轮等待。
      // 只有轮询之外的切页、切日期等用户操作，才开始新的等待周期。
      if (!polling) {
        startedAt = 0
        if (timer !== undefined) window.clearTimeout(timer)
        timer = undefined
      }
    }
    pending = rows.some((row) => (
      row.related_boards?.unavailable_reason === 'first_load_pending'
    ))
    if (pending) {
      if (!startedAt) startedAt = Date.now()
    } else {
      startedAt = 0
      activeContext = context
      if (timer !== undefined) window.clearTimeout(timer)
      timer = undefined
    }
    schedule()
  }

  onBeforeUnmount(() => {
    disposed = true
    pending = false
    if (timer !== undefined) window.clearTimeout(timer)
    timer = undefined
  })

  return { observe }
}
