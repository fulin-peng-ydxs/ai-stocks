import { useAsyncResultPolling } from '@/composables/useAsyncResultPolling'
import type { StockRelatedBoards } from '@/types/relatedBoards'

export interface RelatedBoardRow {
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
  businessDate: string | null | ((row: T) => string | null | undefined),
): string {
  return rows
    .map((row) => {
      const rowDate = typeof businessDate === 'function' ? businessDate(row) : businessDate
      return `${row.code ?? ''}@${rowDate ?? ''}`
    })
    .sort()
    .join('|')
}

/** 静默轮询只回填走势摘要，保留页面行对象和其它业务字段，避免触发整表与分析区刷新。 */
export function mergeRelatedBoardResults<T extends RelatedBoardRow>(
  currentRows: T[],
  incomingRows: RelatedBoardRow[],
): void {
  const incomingByCode = new Map(
    incomingRows.map((row) => [String(row.code ?? ''), row.related_boards ?? null]),
  )
  currentRows.forEach((row) => {
    const code = String(row.code ?? '')
    if (incomingByCode.has(code)) row.related_boards = incomingByCode.get(code)
  })
}

/**
 * 统一观察四类走势摘要消费页返回的首次计算状态；只轮询调用方已有业务读取接口，
 * 避免普通业务用户依赖 system-only 任务详情权限，也不让各页面复制轮询生命周期。
 */
export function useRelatedBoardFirstLoad(
  refresh: () => unknown | Promise<unknown>,
  options: FirstLoadPollingOptions = {},
) {
  const polling = useAsyncResultPolling(refresh, {
    intervalMs: options.intervalMs,
    timeoutMs: options.timeoutMs,
    // 表格刷新会因行情排序变化带回另一页股票，这不代表用户切换了读取上下文。
    resetContextDuringRefresh: false,
  })

  function observe(rows: RelatedBoardRow[], context = ''): void {
    polling.observe(
      rows.some((row) => row.related_boards?.unavailable_reason === 'first_load_pending'),
      context,
    )
  }

  return { observe }
}
