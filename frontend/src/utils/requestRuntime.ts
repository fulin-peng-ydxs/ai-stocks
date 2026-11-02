import { formatNumber } from '@/utils/numberFormat'
/** 来源与任务共用的运行统计口径；缺少旧指标时保留未知，不补零伪装已测量。 */
export interface RequestRuntime {
  requests: number
  failures: number
  network_seconds: number
  wait_seconds: number
  active?: number
  waiting?: number
  observed_rate?: number
  cooldown_seconds?: number
  sampled_at?: string
}

export interface TaskRequestRuntime {
  requests: number
  failures: number
  network_seconds: number
  wait_seconds: number
  states: Record<string, number>
  completed: number
  elapsed_seconds: number
  work_concurrency?: number
  configured_work_concurrency?: number
  default_concurrency?: number
  concurrency_origin?: string
  policy_version?: string
  policy_degraded?: boolean
  eta_seconds?: number | null
  db_wait_seconds?: number
  db_execute_seconds?: number
  db_queries?: number
  retry_wait_seconds?: number
}

export function requestRuntimeText(runtime?: RequestRuntime | null): string {
  if (!runtime) return '运行指标暂不可用'
  return `网络在途 ${formatNumber(runtime.active, 'count')} · 等待额度 ${formatNumber(runtime.waiting, 'count')} · 近一分钟 ${formatNumber(runtime.observed_rate, 'decimal')} 次/秒；累计请求 ${formatNumber(runtime.requests, 'count')} 次 · 技术失败 ${formatNumber(runtime.failures, 'count')} 次 · 网络 ${formatNumber(runtime.network_seconds, 'seconds')} 秒 · 额度等待 ${formatNumber(runtime.wait_seconds, 'seconds')} 秒`
}

/** 来源清单与任务详情共用的诊断说明，避免把内容摘要误认为需要填写的配置 ID。 */
export const REQUEST_CONFIG_FINGERPRINT = {
  label: '配置指纹',
  help: '系统根据整组采集相关配置自动生成，用于排查配置是否一致，无需填写。多个来源显示相同指纹是正常的；任务中显示的是最近记录的指纹，不能代表整个任务始终使用同一套配置。',
  degradedText: '配置读取异常，暂用最近有效配置',
}

interface TaskRequestField {
  label: string
  value: string
  help?: string
  warning?: string
}

export function taskRequestFields(runtime?: TaskRequestRuntime | null): TaskRequestField[] {
  if (!runtime) return []
  const states = runtime.states ?? {}
  const configured = runtime.configured_work_concurrency == null
    ? `启动时默认 ${formatNumber(runtime.default_concurrency, 'count', { empty: '未记录' })}`
    : `本阶段配置 ${formatNumber(runtime.configured_work_concurrency, 'count')}`
  return [
    { label: '工作并发', value: runtime.work_concurrency == null ? '未记录' : `${formatNumber(runtime.work_concurrency, 'count')}（${runtime.concurrency_origin === 'task' ? '任务覆盖' : '系统默认'}；${configured}）`, help: '本阶段有效工作单元上限，受待采标的数限制；实际网络在途还受来源共享额度约束。' },
    { label: '工作状态', value: `网络 ${formatNumber(states.network ?? 0, 'count')} · 等待额度 ${formatNumber(states.source_wait ?? 0, 'count')} · 等待落库 ${formatNumber(states.write_queue ?? 0, 'count')} · 处理 ${formatNumber(states.processing ?? 0, 'count')} · 重试退避 ${formatNumber(states.retry_wait ?? 0, 'count')}` },
    { label: '真实请求', value: `${formatNumber(runtime.requests, 'count')} 次，技术失败 ${formatNumber(runtime.failures, 'count')} 次` },
    { label: '累计网络耗时', value: `${formatNumber(runtime.network_seconds, 'seconds')} 秒` },
    { label: '累计额度等待', value: `${formatNumber(runtime.wait_seconds, 'seconds')} 秒` },
    { label: '累计重试退避', value: runtime.retry_wait_seconds == null ? '未记录' : `${formatNumber(runtime.retry_wait_seconds, 'seconds')} 秒`, help: '失败或空响应后的重试间隔，独立于网络和来源额度等待；并发时按线程累计，不等于任务墙钟耗时。' },
    { label: '数据库累计耗时', value: `等锁 ${formatNumber(runtime.db_wait_seconds, 'seconds')} 秒 · 执行 ${formatNumber(runtime.db_execute_seconds, 'seconds')} 秒 · ${formatNumber(runtime.db_queries, 'count')} 次` },
    { label: '当前阶段预计剩余', value: runtime.eta_seconds == null ? '样本不足或阶段已变化' : `约 ${Math.ceil(runtime.eta_seconds / 60)} 分钟` },
    {
      label: REQUEST_CONFIG_FINGERPRINT.label,
      value: runtime.policy_version || '未记录',
      help: REQUEST_CONFIG_FINGERPRINT.help,
      warning: runtime.policy_degraded ? REQUEST_CONFIG_FINGERPRINT.degradedText : undefined,
    },
  ]
}
