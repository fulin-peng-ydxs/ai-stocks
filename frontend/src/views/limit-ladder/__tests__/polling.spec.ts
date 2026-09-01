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

  it('最后一次等待按剩余时间截断并在上限处停止轮询', () => {
    expect(limitLadderPollDecision(3, LIMIT_LADDER_POLL_TIMEOUT_MS - 1)).toEqual({
      timedOut: false,
      delayMs: 1,
    })
    expect(limitLadderPollDecision(4, LIMIT_LADDER_POLL_TIMEOUT_MS)).toEqual({
      timedOut: true,
      delayMs: null,
    })
  })

  it('全部定时器累计不超过 120 秒且到期后没有下一次请求', () => {
    let elapsedMs = 0
    let attempt = 0
    while (elapsedMs < LIMIT_LADDER_POLL_TIMEOUT_MS) {
      const decision = limitLadderPollDecision(attempt, elapsedMs)
      expect(decision.timedOut).toBe(false)
      expect(decision.delayMs).not.toBeNull()
      elapsedMs += decision.delayMs!
      attempt += 1
    }

    expect(elapsedMs).toBe(LIMIT_LADDER_POLL_TIMEOUT_MS)
    expect(limitLadderPollDecision(attempt, elapsedMs)).toEqual({
      timedOut: true,
      delayMs: null,
    })
  })
})
