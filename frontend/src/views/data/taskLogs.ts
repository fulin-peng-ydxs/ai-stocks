import type { TaskLogLine } from '@/api/data'

// 与服务端每任务保留窗口一致，避免长时间打开抽屉累积数万行 DOM。
export const TASK_LOG_LIMIT = 2000

export function appendTaskLogs(current: TaskLogLine[], incoming: TaskLogLine[]): TaskLogLine[] {
  return [...current, ...incoming].slice(-TASK_LOG_LIMIT)
}

export function taskLogMessage(message: string): string {
  // 旧日志保留原始内容；展示时明确说明旧检查点未记录计数，不猜测完成数量。
  return message.replace('约完成 None/? 项', '上次处理计数未记录')
}
