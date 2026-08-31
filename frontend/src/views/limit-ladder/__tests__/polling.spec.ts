import { describe, expect, it } from 'vitest'
import type { LimitLadderResult } from '@/api/limitLadder'
import {
  LIMIT_LADDER_POLL_MAX_MS,
  LIMIT_LADDER_POLL_TIMEOUT_MS,
  limitLadderPollDecision,
  limitLadderPollDelay,
  limitLadderPollTaskKey,
} from '../polling'

describe('limit ladder polling policy', () => {
  it('指数退避并限制最大等待间隔', () => {
    expect([0, 1, 2, 3, 4].map(limitLadderPollDelay)).toEqual([
      1_500,
      3_000,
      6_000,
      12_000,
      LIMIT_LADDER_POLL_MAX_MS,
    ])
  })

  it('以交易日和后端任务标识区分新的轮询周期', () => {
    const result = {
      trade_date: '2026-08-28',
      task: {
        command_id: 'command-1',
        task_id: 'task-1',
        status: 'running',
        source: 'auto_first_load',
      },
    } as LimitLadderResult
    expect(limitLadderPollTaskKey(result)).toBe('2026-08-28:command-1:task-1')
    expect(limitLadderPollTaskKey({
      ...result,
      task: { ...result.task!, task_id: 'task-2' },
    })).toBe('2026-08-28:command-1:task-2')
  })

  it('超过总等待上限后停止轮询', () => {
    expect(limitLadderPollDecision(3, LIMIT_LADDER_POLL_TIMEOUT_MS - 1)).toEqual({
      timedOut: false,
      delayMs: 12_000,
    })
    expect(limitLadderPollDecision(4, LIMIT_LADDER_POLL_TIMEOUT_MS)).toEqual({
      timedOut: true,
      delayMs: null,
    })
  })
})
