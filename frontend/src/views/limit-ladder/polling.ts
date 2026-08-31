import type { LimitLadderResult } from '@/api/limitLadder'

export const LIMIT_LADDER_POLL_BASE_MS = 1_500
export const LIMIT_LADDER_POLL_MAX_MS = 12_000
export const LIMIT_LADDER_POLL_TIMEOUT_MS = 120_000

export function limitLadderPollDelay(attempt: number): number {
  return Math.min(
    LIMIT_LADDER_POLL_MAX_MS,
    LIMIT_LADDER_POLL_BASE_MS * (2 ** Math.max(0, attempt)),
  )
}

export function limitLadderPollDecision(
  attempt: number,
  elapsedMs: number,
): { timedOut: boolean; delayMs: number | null } {
  if (elapsedMs >= LIMIT_LADDER_POLL_TIMEOUT_MS) {
    return { timedOut: true, delayMs: null }
  }
  return { timedOut: false, delayMs: limitLadderPollDelay(attempt) }
}

export function limitLadderPollTaskKey(result: LimitLadderResult): string {
  return [
    result.trade_date,
    result.task?.command_id || 'no-command',
    result.task?.task_id || 'no-task',
  ].join(':')
}
