// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { useDebouncedQuery } from '@/composables/useDebouncedQuery'

function mountHarness(resetAndReload: () => void, debounceMs = 300) {
  let api!: ReturnType<typeof useDebouncedQuery>
  const Harness = defineComponent({
    setup() {
      api = useDebouncedQuery(resetAndReload, debounceMs)
      return () => null
    },
  })
  const wrapper = mount(Harness)
  return { api, wrapper }
}

describe('useDebouncedQuery', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('schedule 防抖：连续调用只在间隔后触发一次', () => {
    const reload = vi.fn()
    const { api } = mountHarness(reload)
    api.schedule()
    api.schedule()
    api.schedule()
    expect(reload).not.toHaveBeenCalled()
    vi.advanceTimersByTime(299)
    expect(reload).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('flush 立即触发，并取消未决的防抖队列', () => {
    const reload = vi.fn()
    const { api } = mountHarness(reload)
    api.schedule()
    api.flush()
    expect(reload).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(300)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('cancel 后不再触发', () => {
    const reload = vi.fn()
    const { api } = mountHarness(reload)
    api.schedule()
    api.cancel()
    vi.advanceTimersByTime(300)
    expect(reload).not.toHaveBeenCalled()
  })

  it('卸载时取消未决防抖，避免路由切换后误触发', () => {
    const reload = vi.fn()
    const { api, wrapper } = mountHarness(reload)
    api.schedule()
    wrapper.unmount()
    vi.advanceTimersByTime(300)
    expect(reload).not.toHaveBeenCalled()
  })
})
