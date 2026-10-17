// @vitest-environment jsdom
import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { usePageShortcuts } from '../usePageShortcuts'

function key(init: KeyboardEventInit = {}) {
  const event = new KeyboardEvent('keydown', { key: 'b', bubbles: true, cancelable: true, ...init })
  document.body.dispatchEvent(event)
  return event
}
it('页面命令遵守启用边界、防异步重入、错误反馈与 KeepAlive 清理', async () => {
  let finish!: () => void
  const run = vi.fn(() => new Promise<void>(resolve => { finish = resolve }))
  const onError = vi.fn(), enabled = ref(true), show = ref(true)
  const page = defineComponent({ setup() {
    usePageShortcuts([{ key: 'b', run }], { enabled: () => enabled.value, onError })
    return () => null
  } })
  const wrapper = mount(defineComponent({ components: { Page: page }, setup: () => ({ show }), template: '<KeepAlive><Page v-if="show"/></KeepAlive>' }))
  expect(key().defaultPrevented).toBe(true)
  key(); expect(run).toHaveBeenCalledTimes(1)
  finish(); await flushPromises()
  enabled.value = false; expect(key().defaultPrevented).toBe(false)
  enabled.value = true; show.value = false; await wrapper.vm.$nextTick()
  key(); expect(run).toHaveBeenCalledTimes(1)
  show.value = true; await wrapper.vm.$nextTick()
  run.mockRejectedValueOnce(new Error('失败'))
  key(); await flushPromises(); expect(onError).toHaveBeenCalledOnce()
  key({ repeat: true }); key({ ctrlKey: true }); expect(run).toHaveBeenCalledTimes(2)
  wrapper.unmount(); key(); expect(run).toHaveBeenCalledTimes(2)
})
