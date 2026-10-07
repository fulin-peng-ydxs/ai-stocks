// @vitest-environment jsdom
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { vReveal } from '../reveal'

const Fixture = defineComponent({
  props: { value: { type: [String, Boolean], default: false }, page: Boolean },
  directives: { reveal: vReveal },
  template: `<div v-reveal:page="value" :style="{ display: page ? 'contents' : 'block' }"
    style="--app-motion-page:180ms;--app-motion-ease:ease-out"><input /><span>内容</span></div>`,
})

let reduced = false
let preferenceChange: (() => void) | undefined
const cancel = vi.fn()
const animate = vi.fn()
const remove = vi.fn()
let wrappers: ReturnType<typeof mount>[] = []
function render(props: Record<string, unknown>) {
  const wrapper = mount(Fixture, { props })
  wrappers.push(wrapper)
  return wrapper
}

beforeEach(() => {
  reduced = false
  preferenceChange = undefined
  animate.mockReset().mockImplementation(() => ({ cancel, finished: new Promise(() => {}) }))
  cancel.mockReset()
  remove.mockReset()
  vi.stubGlobal('matchMedia', () => ({ matches: reduced,
    addEventListener: (_event: string, listener: () => void) => { preferenceChange = listener },
    removeEventListener: remove,
  }))
  Object.defineProperty(Element.prototype, 'animate', { configurable: true, value: animate })
})
afterEach(() => {
  wrappers.forEach((wrapper) => wrapper.unmount())
  wrappers = []
  vi.unstubAllGlobals()
  Reflect.deleteProperty(Element.prototype, 'animate')
})

describe('共享显现动效', () => {
  it('无内容不播放，内容就绪播放一次，同状态更新不重播且保留节点', async () => {
    const wrapper = render({ value: false })
    const input = wrapper.get('input').element
    expect(animate).not.toHaveBeenCalled()
    await wrapper.setProps({ value: true })
    expect(animate).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ value: true })
    expect(animate).toHaveBeenCalledTimes(1)
    expect(wrapper.get('input').element).toBe(input)
    await wrapper.setProps({ value: false })
    expect(cancel).toHaveBeenCalledTimes(1)
  })

  it('display:contents 对真实根节点播放，快速切换取消旧动画', async () => {
    const wrapper = render({ value: '/one', page: true })
    expect(animate).toHaveBeenCalledTimes(2)
    expect(animate.mock.calls[0][1]).toMatchObject({ duration: 180 })
    expect(animate.mock.calls[0][0][0]).toMatchObject({ translate: '0 4px' })
    await wrapper.setProps({ value: '/two' })
    expect(cancel).toHaveBeenCalledTimes(2)
    expect(animate).toHaveBeenCalledTimes(4)
    wrapper.unmount()
    wrappers = []
    expect(cancel).toHaveBeenCalledTimes(4)
    expect(remove).toHaveBeenCalledTimes(2)
  })

  it('减少动画时直接显示，运行中更改偏好释放动画', async () => {
    reduced = true
    const wrapper = render({ value: '/one' })
    expect(animate).not.toHaveBeenCalled()
    reduced = false
    await wrapper.setProps({ value: '/two' })
    expect(animate).toHaveBeenCalledTimes(1)
    preferenceChange?.()
    expect(cancel).toHaveBeenCalledTimes(1)
  })

  it('内容显现保持原位，不对表格和画布增加位移', () => {
    const Content = defineComponent({
      directives: { reveal: vReveal },
      template: '<div v-reveal="true" style="--app-motion-content:180ms">内容</div>',
    })
    const wrapper = mount(Content)
    wrappers.push(wrapper)
    expect(animate.mock.calls[0][0]).toEqual([{ opacity: 0.35 }, { opacity: 1 }])
  })

  it('正常结束后释放动画和偏好监听，不残留透明度效果', async () => {
    animate.mockImplementation(() => ({ cancel, finished: Promise.resolve() }))
    render({ value: true })
    await flushPromises()
    expect(cancel).toHaveBeenCalledTimes(1)
    expect(remove).toHaveBeenCalledTimes(1)
  })

  it('缺少动画 API 时内容仍正常渲染', () => {
    Reflect.deleteProperty(Element.prototype, 'animate')
    expect(render({ value: true }).text()).toContain('内容')
  })
})
