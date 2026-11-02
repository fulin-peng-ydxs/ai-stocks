import { onBeforeUnmount } from 'vue'

export interface AsyncResultPollingOptions {
  intervalMs?: number
  /** 0 表示持续跟踪持久化等待请求，停止与卸载仍会清理轮询。 */
  timeoutMs?: number
  /** 服务端绝对期限；提供时优先使用，不随轮询响应续期。 */
  deadlineAt?: () => number | undefined
  delayMs?: (attempt: number) => number
  resetContextDuringRefresh?: boolean
  onTimeout?: () => void
}

/**
 * 异步结果统一轮询生命周期：绝对超时、单请求串行、上下文切换和卸载清理。
 * 调用方只负责把业务状态归一成 pending/context，并按任务成本提供轮询间隔策略。
 */
export function useAsyncResultPolling(
  refresh: () => unknown | Promise<unknown>,
  options: AsyncResultPollingOptions = {},
) {
  const intervalMs = options.intervalMs ?? 1500
  const timeoutMs = options.timeoutMs ?? 120_000
  const resetContextDuringRefresh = options.resetContextDuringRefresh ?? true
  const delayMs = options.delayMs ?? (() => intervalMs)
  let pollTimer: number | undefined
  let deadlineTimer: number | undefined
  let polling = false
  let disposed = false
  let pending = false
  let startedAt = 0
  let attempt = 0
  let activeContext = ''
  let timedOut = false
  let timedOutContext = ''

  function clearTimers(): void {
    if (pollTimer !== undefined) window.clearTimeout(pollTimer)
    if (deadlineTimer !== undefined) window.clearTimeout(deadlineTimer)
    pollTimer = undefined
    deadlineTimer = undefined
  }

  function finishTimeout(): void {
    if (!pending || disposed) return
    pending = false
    timedOut = true
    timedOutContext = activeContext
    clearTimers()
    options.onTimeout?.()
  }

  function startCycle(context: string): void {
    clearTimers()
    activeContext = context
    timedOut = false
    timedOutContext = ''
    startedAt = Date.now()
    attempt = 0
    const deadline = options.deadlineAt?.()
    const absoluteDeadline = typeof deadline === 'number' && Number.isFinite(deadline)
    if (absoluteDeadline || timeoutMs > 0) {
      const remaining = absoluteDeadline ? Math.max(0, deadline - Date.now()) : timeoutMs
      deadlineTimer = window.setTimeout(finishTimeout, remaining)
    }
  }

  function schedule(): void {
    if (disposed || polling || !pending || pollTimer !== undefined) return
    const delay = Math.max(0, Number(delayMs(attempt)) || 0)
    pollTimer = window.setTimeout(() => {
      pollTimer = undefined
      attempt += 1
      void poll()
    }, delay)
  }

  async function poll(): Promise<void> {
    if (disposed || polling || !pending) return
    polling = true
    try {
      await refresh()
    } finally {
      polling = false
      schedule()
    }
  }

  function stop(): void {
    pending = false
    startedAt = 0
    attempt = 0
    activeContext = ''
    timedOut = false
    timedOutContext = ''
    clearTimers()
  }

  function observe(isPending: boolean, context = ''): void {
    if (disposed) return
    const contextChanged = Boolean(context && context !== activeContext)
    if (contextChanged && (!polling || resetContextDuringRefresh)) {
      startCycle(context)
    } else if (contextChanged) {
      // 轮询自身带回的数据范围变化只更新标识，不延长当前绝对时限。
      activeContext = context
    }
    if (!isPending) {
      stop()
      return
    }
    // 超时请求的迟到响应不能复活同一轮轮询；用户后续主动请求发生在 polling=false，
    // 仍可用相同上下文开始新的等待周期。
    if (polling && timedOut && timedOutContext === (context || activeContext)) return
    pending = true
    if (!startedAt || (!polling && timedOut)) {
      startCycle(context || activeContext)
    }
    schedule()
  }

  onBeforeUnmount(() => {
    disposed = true
    pending = false
    clearTimers()
  })

  return { observe, stop }
}
