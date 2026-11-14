import { STATUS_LABEL, type AsyncTask } from '@/api/data'
import { businessMessage, enumText } from './displayText'
import { formatDateTimeSeconds } from './dateTime'

type TaskTone = 'success' | 'danger' | 'info' | 'warning'
const STATUS_TONE: Record<string, TaskTone> = {
  done: 'success', failed: 'danger', running: 'warning', pending: 'info', interrupted: 'danger',
}

function count(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : undefined
}

/** 只解释已结束任务的业务结果；执行状态、调度依赖和筛选仍使用服务端原值。 */
export function taskOutcomeDisplay(task: Pick<AsyncTask, 'task_type' | 'status' | 'result' | 'message' | 'params' | 'cancel_requested_at'>) {
  const cancelling = task.status === 'running' && Boolean(task.cancel_requested_at)
  const executionLabel = enumText(STATUS_LABEL, task.status, '状态未识别')
  const result = task.result
  const failedRepair = task.task_type === 'fix' && (task.status === 'failed'
    || (task.status === 'done' && result?.ok === false))
  // 新任务提供安全的失败原因；旧任务仍保留原有可读文案。
  const failureReason = failedRepair ? businessMessage(result?.failure_reason,
    businessMessage(task.message, '')) : ''
  // 修复的技术原文仍由日志承接，但普通反馈须保留结果及质量台账的处置入口。
  const repairFallback = task.status === 'done' && task.result?.ok === true
    ? '恢复完成，复检通过'
    : task.status === 'interrupted'
      ? '恢复已中断，未完成的问题仍待处理，可重新修复'
      : '恢复未完成，问题仍待处理；可查看该问题的诊断详情后重试'
  const original = {
    label: cancelling ? '终止中' : executionLabel,
    tone: cancelling ? 'warning' as const : failedRepair ? 'danger' as const
      : (STATUS_TONE[task.status] ?? 'info'),
    message: failureReason || businessMessage(task.message, task.task_type === 'fix'
      && ['done', 'failed', 'interrupted'].includes(task.status)
      ? repairFallback : '任务执行结果请查看日志'),
  }
  let display = original
  // 旧任务没有结构化计数时保留原说明，不从中文日志猜测结果。
  if (result && (task.status === 'done' || task.status === 'failed')) {
    const technical = Math.max(count(result.failed) ?? 0, count(result.technical_failure) ?? 0)
    const deferred = count(result.deferred) ?? 0
    const unavailable = count(result.unavailable) ?? 0
    const intradayFix = task.task_type === 'fix' && (
      String(task.params?.issue_type ?? '').startsWith('intraday_')
      || Boolean(result.checkpoint?.intraday_repair_checkpoint)
      || ['deferred', 'unavailable', 'improved', 'unchanged'].some((key) => (count(result[key]) ?? 0) > 0)
    )
    if (intradayFix) {
      const total = count(result.total)
      const completed = count(result.scope_completed)
      if (total !== undefined && completed !== undefined && completed <= total
        && count(result.failed) !== undefined) {
        const remaining = total - completed
        const summary = `已解决 ${completed}/${total} 条；剩余 ${remaining} 条，其中等待源更新或复查 ${deferred} 条、当前来源无法覆盖 ${unavailable} 条、技术失败 ${technical} 条`
        // 单项结果同时保留具体原因；统计摘要不能覆盖缺失日期、覆盖范围或失败说明。
        const reason = total === 1 && failureReason ? `；${failureReason}` : ''
        if (technical > 0) display = { label: '技术失败', tone: 'danger', message: summary + reason }
        else if (remaining > 0) {
          const waiting = deferred === remaining
          const retryAt = waiting && typeof result.next_retry_at === 'string'
            ? formatDateTimeSeconds(result.next_retry_at, '') : ''
          display = {
            label: waiting ? '等待来源更新' : unavailable === remaining ? '来源无法覆盖'
              : completed > 0 ? '部分完成' : '修复未完成',
            tone: 'warning',
            message: `${summary}${reason}；问题仍保留在质量台账${waiting ? `，${retryAt ? `建议 ${retryAt} 后复查，` : ''}可用“重新核验”立即取源` : ''}`,
          }
        }
      }
    } else if (task.task_type === 'intraday_ingest') {
      const quality = result.quality
      const counts = ['intraday_gap', 'intraday_partial', 'intraday_invalid']
        .map((key) => count(quality?.[key]))
      if (counts.every((value) => value !== undefined)) {
        const [missing, partial, invalid] = counts as number[]
        const remaining = missing + partial + invalid
        if (technical > 0 || remaining > 0) display = {
          label: technical > 0 ? '技术失败' : '仍有质量问题',
          tone: technical > 0 ? 'danger' : 'warning',
          message: `整日缺失 ${missing}、分钟不完整 ${partial}、数据非法 ${invalid}；等待源更新或复查 ${deferred}、技术失败 ${technical}；未完整数据继续保留在质量台账`,
        }
      }
    }
  }
  return {
    ...display,
    tooltip: `执行状态：${executionLabel}；${display.message}`,
    // 等待来源不是执行异常；也不能把仍有质量问题的已结束采集画成绿色成功。
    progressStatus: display.tone === 'danger' ? 'exception' as const
      : task.status === 'done' && display.tone === 'success' ? 'success' as const : undefined,
  }
}
