import type { LimitLadderResult } from '@/api/limitLadder'

export const LIMIT_LADDER_POLL_BASE_MS = 1_500
export const LIMIT_LADDER_POLL_MAX_MS = 12_000
export const LIMIT_LADDER_POLL_TIMEOUT_MS = 120_000
// 兼容未返回 deadline_at 的旧接口；当前接口以服务端绝对期限为准。
export const LIMIT_LADDER_QUEUE_FALLBACK_TIMEOUT_MS = 900_000

export function limitLadderPollDelay(attempt: number): number {
  return Math.min(
    LIMIT_LADDER_POLL_MAX_MS,
    LIMIT_LADDER_POLL_BASE_MS * (2 ** Math.max(0, attempt)),
  )
}

export function limitLadderPollTaskKey(result: LimitLadderResult): string {
  const snapshotPending = result.business_code === 'SNAPSHOT_PENDING'
    || result.snapshot_status === 'calculating'
    || result.snapshot_status === 'recalculating'
  const phase = snapshotPending
    ? 'snapshot'
    : result.related_board_status === 'calculating'
      || result.related_concept_status === 'calculating'
      ? 'related'
      : 'ready'
  return `${result.trade_date}:${phase}`
}
