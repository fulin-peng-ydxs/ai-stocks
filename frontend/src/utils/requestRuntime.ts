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
  default_concurrency?: number
  concurrency_origin?: string
  policy_version?: string
  policy_degraded?: boolean
  eta_seconds?: number | null
  db_wait_seconds?: number
  db_execute_seconds?: number
  db_queries?: number
}

export function requestRuntimeText(runtime?: RequestRuntime | null): string {
  if (!runtime) return '运行指标暂不可用'
  return `网络在途 ${runtime.active ?? 0} · 等待额度 ${runtime.waiting ?? 0} · 近一分钟 ${(runtime.observed_rate ?? 0).toFixed(1)} 次/秒；累计请求 ${runtime.requests} 次 · 技术失败 ${runtime.failures} 次 · 网络 ${runtime.network_seconds.toFixed(1)} 秒 · 额度等待 ${runtime.wait_seconds.toFixed(1)} 秒`
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
  return [
    { label: '工作并发', value: runtime.work_concurrency == null ? '未记录' : `${runtime.work_concurrency}（${runtime.concurrency_origin === 'task' ? '任务覆盖' : '系统默认'}；启动时默认 ${runtime.default_concurrency ?? '未记录'}）` },
    { label: '工作状态', value: `网络 ${states.network ?? 0} · 等待额度 ${states.source_wait ?? 0} · 等待落库 ${states.write_queue ?? 0} · 处理 ${states.processing ?? 0}` },
    { label: '真实请求', value: `${runtime.requests} 次，技术失败 ${runtime.failures} 次` },
    { label: '累计网络耗时', value: `${runtime.network_seconds.toFixed(1)} 秒` },
    { label: '累计额度等待', value: `${runtime.wait_seconds.toFixed(1)} 秒` },
    { label: '数据库累计耗时', value: `等锁 ${(runtime.db_wait_seconds ?? 0).toFixed(1)} 秒 · 执行 ${(runtime.db_execute_seconds ?? 0).toFixed(1)} 秒 · ${runtime.db_queries ?? 0} 次` },
    { label: '当前阶段预计剩余', value: runtime.eta_seconds == null ? '样本不足或阶段已变化' : `约 ${Math.ceil(runtime.eta_seconds / 60)} 分钟` },
    {
      label: REQUEST_CONFIG_FINGERPRINT.label,
      value: runtime.policy_version || '未记录',
      help: REQUEST_CONFIG_FINGERPRINT.help,
      warning: runtime.policy_degraded ? REQUEST_CONFIG_FINGERPRINT.degradedText : undefined,
    },
  ]
}
