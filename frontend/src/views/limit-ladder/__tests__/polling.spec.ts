import { describe, expect, it } from 'vitest'
import type { LimitLadderResult } from '@/api/limitLadder'
import {
  LIMIT_LADDER_POLL_MAX_MS,
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

  it('同一交易日同一阶段共享截止时间，快照与走势计算各自计时', () => {
    const result = {
      trade_date: '2026-08-28',
      business_code: 'SNAPSHOT_PENDING',
      snapshot_status: 'calculating',
      task: {
        command_id: 'command-1',
        task_id: 'task-1',
        status: 'running',
        source: 'auto_first_load',
      },
    } as LimitLadderResult
    expect(limitLadderPollTaskKey(result)).toBe('2026-08-28:snapshot')
    expect(limitLadderPollTaskKey({
      ...result,
      task: { ...result.task!, task_id: 'task-2' },
    })).toBe('2026-08-28:snapshot')
    expect(limitLadderPollTaskKey({
      ...result,
      task: { ...result.task!, command_id: '', task_id: 'task-2' },
    })).toBe('2026-08-28:snapshot')
    expect(limitLadderPollTaskKey({ ...result, trade_date: '2026-08-29' }))
      .toBe('2026-08-29:snapshot')
    expect(limitLadderPollTaskKey({
      ...result,
      business_code: 'READY',
      snapshot_status: 'valid',
      related_board_status: 'calculating',
    })).toBe('2026-08-28:related')
  })
})
