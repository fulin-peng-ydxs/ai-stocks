// @vitest-environment jsdom

import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRelatedBoardFirstLoad } from '../useRelatedBoardFirstLoad'

describe('useRelatedBoardFirstLoad', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('计算中时轮询业务查询，刷新结果就绪后停止', async () => {
    const refresh = vi.fn()
    let observe!: ReturnType<typeof useRelatedBoardFirstLoad>['observe']
    const wrapper = mount(defineComponent({
      setup() {
        ;({ observe } = useRelatedBoardFirstLoad(refresh, { intervalMs: 10 }))
        return () => null
      },
    }))

    const pending = {
      related_boards: {
        as_of_date: null,
        benchmark: { code: null, name: null, fallback: false },
        industry: null,
        concept: null,
        unavailable_reason: 'first_load_pending' as const,
      },
    }
    observe([pending, pending])
    await vi.advanceTimersByTimeAsync(10)

    expect(refresh).toHaveBeenCalledTimes(1)
    observe([])
    await vi.advanceTimersByTimeAsync(20)
    expect(refresh).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('组件卸载后停止尚未开始的轮询', async () => {
    const refresh = vi.fn()
    let observe!: ReturnType<typeof useRelatedBoardFirstLoad>['observe']
    const wrapper = mount(defineComponent({
      setup() {
        ;({ observe } = useRelatedBoardFirstLoad(refresh, { intervalMs: 10 }))
        return () => null
      },
    }))
    observe([{
      related_boards: {
        as_of_date: null,
        benchmark: { code: null, name: null, fallback: false },
        industry: null,
        concept: null,
        unavailable_reason: 'first_load_pending',
      },
    }])

    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(20)

    expect(refresh).not.toHaveBeenCalled()
  })

  it('切换股票或业务日期后重新计算等待时限', async () => {
    const refresh = vi.fn()
    let observe!: ReturnType<typeof useRelatedBoardFirstLoad>['observe']
    const wrapper = mount(defineComponent({
      setup() {
        ;({ observe } = useRelatedBoardFirstLoad(refresh, { intervalMs: 10, timeoutMs: 25 }))
        return () => null
      },
    }))
    const pending = (code: string) => ({
      code,
      related_boards: {
        as_of_date: null,
        benchmark: { code: null, name: null, fallback: false },
        industry: null,
        concept: null,
        unavailable_reason: 'first_load_pending' as const,
      },
    })

    observe([pending('600000.SH')], '600000.SH@2026-08-28')
    await vi.advanceTimersByTimeAsync(20)
    observe([pending('000001.SZ')], '000001.SZ@2026-08-27')
    await vi.advanceTimersByTimeAsync(20)

    expect(refresh).toHaveBeenCalledTimes(4)
    await vi.advanceTimersByTimeAsync(20)
    expect(refresh).toHaveBeenCalledTimes(5)
    wrapper.unmount()
  })

  it('轮询刷新导致当前页股票变化时不重置绝对等待时限', async () => {
    let observe!: ReturnType<typeof useRelatedBoardFirstLoad>['observe']
    let sequence = 0
    const pending = (code: string) => ({
      code,
      related_boards: {
        as_of_date: null,
        benchmark: { code: null, name: null, fallback: false },
        industry: null,
        concept: null,
        unavailable_reason: 'first_load_pending' as const,
      },
    })
    const refresh = vi.fn(() => {
      sequence += 1
      const code = `60000${sequence}.SH`
      observe([pending(code)], `${code}@2026-09-02`)
    })
    const wrapper = mount(defineComponent({
      setup() {
        ;({ observe } = useRelatedBoardFirstLoad(refresh, {
          intervalMs: 10,
          timeoutMs: 25,
        }))
        return () => null
      },
    }))

    observe([pending('600000.SH')], '600000.SH@2026-09-02')
    await vi.advanceTimersByTimeAsync(60)

    expect(refresh).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(60)
    expect(refresh).toHaveBeenCalledTimes(3)
    wrapper.unmount()
  })
})
