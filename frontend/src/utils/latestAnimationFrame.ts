export interface LatestAnimationFrame<T> {
  schedule: (value: T) => void
  flush: () => void
  cancel: () => void
}

/**
 * 合并同一绘制帧内的高频更新，只把最新值交给消费方。
 * flush 用于 pointerup 等终态，确保最后位置不会滞留到下一帧。
 */
export function createLatestAnimationFrame<T>(
  apply: (value: T) => void,
): LatestAnimationFrame<T> {
  let frame: number | null = null
  let pending = false
  let latest: T

  function run(): void {
    frame = null
    if (!pending) return
    pending = false
    apply(latest)
  }

  function schedule(value: T): void {
    latest = value
    pending = true
    if (frame !== null) return
    frame = requestAnimationFrame(run)
  }

  function flush(): void {
    if (!pending) return
    if (frame !== null) cancelAnimationFrame(frame)
    run()
  }

  function cancel(): void {
    if (frame !== null) cancelAnimationFrame(frame)
    frame = null
    pending = false
  }

  return { schedule, flush, cancel }
}
