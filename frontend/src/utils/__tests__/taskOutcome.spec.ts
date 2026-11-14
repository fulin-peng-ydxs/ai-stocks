import { describe, expect, it } from 'vitest'
import { taskOutcomeDisplay } from '@/utils/taskOutcome'
import type { AsyncTask } from '@/api/data'
import { ISSUE_TYPE_LABEL } from '@/api/data'

const repair: Pick<AsyncTask, 'task_type' | 'status' | 'result' | 'message' | 'params'> = {
  task_type: 'fix', status: 'failed', message: '原始修复说明',
  params: { issue_type: 'intraday_partial' },
  result: { total: 1, scope_completed: 0, failed: 0, technical_failure: 0, deferred: 1 },
}

describe('任务业务结果展示', () => {
  it.each(Object.keys(ISSUE_TYPE_LABEL))('%s 单项修复优先显示明确原因，兼容缺失统计的规划失败', (issueType) => {
    const failure_reason = '数据源请求超时，未能完成取数，请稍后重试'
    const task = { ...repair, params: { issue_id: 1, issue_type: issueType },
      message: 'HTTPError: https://secret.test/private', result: { failure_reason } }
    expect(taskOutcomeDisplay(task)).toMatchObject({ message: failure_reason, tone: 'danger' })
    const complete = taskOutcomeDisplay({ ...task, result: {
      failure_reason, total: 1, scope_completed: 0, failed: 1,
    } })
    expect(complete.message).toContain(failure_reason)
    expect(complete.message).not.toContain('secret')
    expect(complete.message).not.toContain('查看日志')
  })

  it('分时单项等待来源保留具体缺失日期和原因，批量不冒用单项原因', () => {
    const failure_reason = '2026-11-13 缺失 60 分钟，来源响应尚未覆盖下午时段'
    expect(taskOutcomeDisplay({ ...repair, result: { ...repair.result, failure_reason } }).message)
      .toContain(failure_reason)
    expect(taskOutcomeDisplay({ ...repair, result: {
      ...repair.result, total: 2, failure_reason,
    } }).message).not.toContain(failure_reason)
  })

  it('失败原因仍经过安全展示检查，成功和运行中的任务不消费残留失败原因', () => {
    const task = { ...repair, params: { issue_type: 'capital_gap' }, message: '来源尚未提供完整股本数据',
      result: { failure_reason: '数据库异常 SQL: SELECT secret FROM private_table' } }
    expect(taskOutcomeDisplay(task).message).toBe(task.message)
    for (const status of ['pending', 'running', 'interrupted', 'done'] as const) {
      expect(taskOutcomeDisplay({ ...task, status, message: '当前任务状态说明',
        result: { ok: true, failure_reason: '不应显示的旧失败原因' },
      }).message).toBe('当前任务状态说明')
    }
  })
  it('单项 ST 修复直接保留事实缺失原因，技术原文兜底也保留质量处置入口', () => {
    const message = '恢复失败，已退回待处理：ST 状态刷新失败：002731.SZ ST 点时事实缺 1 个行情日，示例: 2026-11-13'
    const task = { ...repair, params: { issue_type: 'st_status_missing' },
      message, result: { ok: false, total: 1, scope_completed: 0, failed: 1 } }
    expect(taskOutcomeDisplay(task)).toMatchObject({ message, tone: 'danger' })
    const legacy = taskOutcomeDisplay({ ...task,
      message: "恢复失败，已退回待处理：ST 状态刷新失败：[{'code': '002731.SZ', 'error': '事实缺失'}]" })
    expect(legacy.message).toContain('问题仍待处理')
    expect(legacy.message).toContain('诊断详情')
    expect(legacy.message).not.toContain('查看日志')
    expect(legacy.message).not.toContain('error')
  })

  it('修复的安全兜底区分成功、失败和中断，不泄露技术细节', () => {
    const task = { ...repair, params: { issue_type: 'stale' }, message: 'HTTPError https://example.test/private' }
    expect(taskOutcomeDisplay({ ...task, status: 'done', result: { ok: true } }).message)
      .toBe('恢复完成，复检通过')
    expect(taskOutcomeDisplay({ ...task, status: 'done', result: { ok: false } }).message)
      .toContain('恢复未完成')
    expect(taskOutcomeDisplay({ ...task, status: 'interrupted' }).message).toContain('恢复已中断')
    expect(taskOutcomeDisplay({ ...task, task_type: 'verify' }).message).toBe('任务执行结果请查看日志')
  })

  it('真实修复的等待来源结果显示警告，保留执行状态及复查时间', () => {
    const task = { ...repair, result: { ...repair.result, next_retry_at: '2026-10-28T02:05:34.707+08:00' } }
    const display = taskOutcomeDisplay(task)
    expect(display).toMatchObject({ label: '等待来源更新', tone: 'warning', progressStatus: undefined })
    expect(display.message).toContain('已解决 0/1 条')
    expect(display.message).toContain('2026-10-28 02:05:34 后复查')
    expect(display.message).toContain('“重新核验”立即取源')
    expect(display.tooltip).toContain('执行状态：失败')
    expect(task.status).toBe('failed')
  })

  it('真实 705/709 修复中技术失败优先，不能被等待来源掩盖', () => {
    const display = taskOutcomeDisplay({ ...repair,
      result: { total: 709, scope_completed: 705, failed: 3, technical_failure: 3, deferred: 1 },
    })
    expect(display).toMatchObject({ label: '技术失败', tone: 'danger', progressStatus: 'exception' })
    expect(display.message).toContain('已解决 705/709 条')
    expect(display.message).toContain('技术失败 3 条')
    expect(display.message).toContain('等待源更新或复查 1 条')
  })

  it('不把未改善、部分改善与等待混为一类', () => {
    const display = taskOutcomeDisplay({ ...repair,
      result: { total: 5, scope_completed: 2, failed: 0, deferred: 1, improved: 1, unchanged: 1 },
    })
    expect(display).toMatchObject({ label: '部分完成', tone: 'warning' })
    expect(display.message).toContain('剩余 3 条')
    expect(display.message).not.toContain('后复查')
  })

  it('来源范围无法覆盖仍保留台账，不能展示完成', () => {
    const display = taskOutcomeDisplay({ ...repair,
      result: { total: 1, scope_completed: 0, failed: 0, unavailable: 1 },
    })
    expect(display).toMatchObject({ label: '来源无法覆盖', tone: 'warning' })
    expect(display.message).toContain('问题仍保留在质量台账')
  })

  it('最终修复全部通过，沿用成功状态', () => {
    expect(taskOutcomeDisplay({ ...repair, status: 'done', message: '全部解决',
      result: { total: 1, scope_completed: 1, failed: 0, deferred: 0, ok: true },
    })).toMatchObject({ label: '已完成', tone: 'success', message: '全部解决', progressStatus: 'success' })
  })

  it('显式 ID 批量修复可从分时检查点识别；其他领域恢复保留原始原因', () => {
    expect(taskOutcomeDisplay({ ...repair, params: { issue_ids: [1, 2] },
      result: { total: 2, scope_completed: 1, failed: 1, technical_failure: 1,
        checkpoint: { intraday_repair_checkpoint: {} } },
    })).toMatchObject({ label: '技术失败' })
    expect(taskOutcomeDisplay({ ...repair, params: { issue_type: 'board_fund_missing' },
      result: { total: 1, scope_completed: 0, failed: 0 },
    })).toMatchObject({ label: '失败', message: '原始修复说明' })
    expect(taskOutcomeDisplay({ ...repair,
      result: { total: 1, scope_completed: 0, failed: 0, unchanged: 1 },
    })).toMatchObject({ label: '修复未完成' })
  })

  const quality = { intraday_gap: 0, intraday_partial: 1, intraday_invalid: 0 }
  it('采集执行完成但数据不全，状态和进度不宣称成功', () => {
    const display = taskOutcomeDisplay({ ...repair, task_type: 'intraday_ingest', status: 'done',
      result: { quality, failed: 0, deferred: 1 },
    })
    expect(display).toMatchObject({ label: '仍有质量问题', tone: 'warning', progressStatus: undefined })
    expect(display.message).toContain('分钟不完整 1')
    expect(display.tooltip).toContain('执行状态：已完成')
  })

  it('备用源已补齐的历史请求错误不会再被判成技术失败', () => {
    expect(taskOutcomeDisplay({ ...repair, task_type: 'intraday_ingest', status: 'done',
      result: { quality: { ...quality, intraday_partial: 0 }, failed: 0, errors: ['主源请求失败，已补齐'] },
    })).toMatchObject({ label: '已完成', tone: 'success' })
  })

  it('仍有技术错误的采集即使归档已完整也不能隐藏失败', () => {
    expect(taskOutcomeDisplay({ ...repair, task_type: 'intraday_ingest',
      result: { quality: { ...quality, intraday_partial: 0 }, failed: 1 },
    })).toMatchObject({ label: '技术失败', tone: 'danger' })
  })

  it.each(['pending', 'running', 'interrupted'] as const)('不把 %s 的旧结果误作终态', (status) => {
    expect(taskOutcomeDisplay({ ...repair, status }).label).not.toBe('等待来源更新')
  })

  it('保留终止中状态和旧任务缺失计数的说明', () => {
    expect(taskOutcomeDisplay({ ...repair, status: 'running', cancel_requested_at: '2026-10-28' }))
      .toMatchObject({ label: '终止中', tone: 'warning' })
    expect(taskOutcomeDisplay({ ...repair, result: { ok: false } }))
      .toMatchObject({ label: '失败', message: '原始修复说明' })
    expect(taskOutcomeDisplay({ ...repair, task_type: 'verify' })).toMatchObject({ label: '失败' })
  })
})
