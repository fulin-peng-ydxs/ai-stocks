import { describe, expect, it } from 'vitest'
import { appendTaskLogs, taskLogMessage, TASK_LOG_LIMIT } from '../taskLogs'
import type { TaskLogLine } from '@/api/data'

const line = (seq: number): TaskLogLine => ({ seq, ts: '2026-10-20 13:00:00', level: 'info', message: `采集 ${seq}` })

describe('任务实时日志', () => {
  it('连续追加保留最新窗口及序号，不无限增加渲染行数', () => {
    const current = Array.from({ length: TASK_LOG_LIMIT }, (_, i) => line(i + 1))
    const result = appendTaskLogs(current, [line(2001), line(2002)])
    expect(result).toHaveLength(TASK_LOG_LIMIT)
    expect(result[0]?.seq).toBe(3)
    expect(result.at(-1)?.seq).toBe(2002)
    expect(current[0]?.seq).toBe(1)
  })

  it('单批超过窗口也只保留最新记录', () => {
    const result = appendTaskLogs([], Array.from({ length: 5000 }, (_, i) => line(i + 1)))
    expect(result).toHaveLength(TASK_LOG_LIMIT)
    expect(result[0]?.seq).toBe(3001)
  })

  it('兼容旧续跑提示且不更改准确计数或源错误', () => {
    expect(taskLogMessage('从检查点继续：约完成 None/? 项；跳过已完成部分'))
      .toBe('从检查点继续：上次处理计数未记录；跳过已完成部分')
    expect(taskLogMessage('已成功完成 14/5219 只')).toBe('已成功完成 14/5219 只')
    expect(taskLogMessage('东财取源失败：ConnectionError')).toBe('东财取源失败：ConnectionError')
  })
})
