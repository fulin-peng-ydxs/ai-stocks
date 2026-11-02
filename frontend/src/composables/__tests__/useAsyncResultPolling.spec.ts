// @vitest-environment jsdom

import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAsyncResultPolling } from '../useAsyncResultPolling'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('useAsyncResultPolling', () => {
  it('服务端绝对期限不会因切换上下文而续期', async () => {
    vi.useFakeTimers()
    const deadline = Date.now() + 50
    const onTimeout = vi.fn()
    let polling!: ReturnType<typeof useAsyncResultPolling>
    const wrapper = mount(defineComponent({
      setup() {
        polling = useAsyncResultPolling(vi.fn(), {
          timeoutMs: 1000, intervalMs: 10, deadlineAt: () => deadline, onTimeout,
        })
        return () => null
      },
    }))
    polling.observe(true, 'first')
    await vi.advanceTimersByTimeAsync(40)
    polling.observe(true, 'second')
    await vi.advanceTimersByTimeAsync(9)
    expect(onTimeout).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(onTimeout).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('持久化等待请求可持续跟踪，停止后不再请求', async () => {
    vi.useFakeTimers()
    const refresh = vi.fn()
    const onTimeout = vi.fn()
    let polling!: ReturnType<typeof useAsyncResultPolling>
    const wrapper = mount(defineComponent({
      setup() {
        polling = useAsyncResultPolling(refresh, { timeoutMs: 0, intervalMs: 12_000, onTimeout })
        return () => null
      },
    }))
    polling.observe(true, 'waiting')
    await vi.advanceTimersByTimeAsync(180_000)
    expect(refresh).toHaveBeenCalledTimes(15)
    expect(onTimeout).not.toHaveBeenCalled()
    polling.stop()
    await vi.advanceTimersByTimeAsync(24_000)
    expect(refresh).toHaveBeenCalledTimes(15)
    wrapper.unmount()
  })

  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('统一按可配置间隔串行轮询并在绝对时限停止', async () => {
    const slow = deferred<void>()
    const refresh = vi.fn(() => slow.promise)
    const onTimeout = vi.fn()
    let polling!: ReturnType<typeof useAsyncResultPolling>
    const wrapper = mount(defineComponent({
      setup() {
        polling = useAsyncResultPolling(refresh, {
          timeoutMs: 25,
          delayMs: (attempt) => 10 * (attempt + 1),
          onTimeout,
        })
        return () => null
      },
    }))

    polling.observe(true, '2026-09-02:snapshot')
    await vi.advanceTimersByTimeAsync(10)
    expect(refresh).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(15)
    expect(onTimeout).toHaveBeenCalledTimes(1)

    slow.resolve()
    await vi.runAllTimersAsync()
    expect(refresh).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('阶段上下文变化时重新开始等待周期', async () => {
    const refresh = vi.fn()
    const onTimeout = vi.fn()
    let polling!: ReturnType<typeof useAsyncResultPolling>
    const wrapper = mount(defineComponent({
      setup() {
        polling = useAsyncResultPolling(refresh, {
          intervalMs: 10,
          timeoutMs: 25,
          onTimeout,
        })
        return () => null
      },
    }))

    polling.observe(true, '2026-09-02:snapshot')
    await vi.advanceTimersByTimeAsync(20)
    polling.observe(true, '2026-09-02:related')
    await vi.advanceTimersByTimeAsync(20)
    expect(onTimeout).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(5)
    expect(onTimeout).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('停止后卸载均不会保留定时请求', async () => {
    const refresh = vi.fn()
    let polling!: ReturnType<typeof useAsyncResultPolling>
    const wrapper = mount(defineComponent({
      setup() {
        polling = useAsyncResultPolling(refresh, { intervalMs: 10 })
        return () => null
      },
    }))

    polling.observe(true, 'context')
    polling.stop()
    await vi.advanceTimersByTimeAsync(20)
    expect(refresh).not.toHaveBeenCalled()

    polling.observe(true, 'context')
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(20)
    expect(refresh).not.toHaveBeenCalled()
  })

  it('超时后同一上下文只有再次观察才开始新一轮', async () => {
    const refresh = vi.fn()
    const onTimeout = vi.fn()
    let polling!: ReturnType<typeof useAsyncResultPolling>
    const wrapper = mount(defineComponent({
      setup() {
        polling = useAsyncResultPolling(refresh, {
          intervalMs: 10,
          timeoutMs: 15,
          onTimeout,
        })
        return () => null
      },
    }))

    polling.observe(true, 'same-context')
    await vi.advanceTimersByTimeAsync(20)
    expect(onTimeout).toHaveBeenCalledTimes(1)
    expect(refresh).toHaveBeenCalledTimes(1)

    polling.observe(true, 'same-context')
    await vi.advanceTimersByTimeAsync(10)
    expect(refresh).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
})
