// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElScrollbar, ElTable, ElTableColumn, ElSelect, ElOption } from 'element-plus'
import { defineComponent, h, KeepAlive, ref, markRaw, nextTick } from 'vue'
import AppScrollArea from '@/components/AppScrollArea.vue'
import AppAsyncRegion from '@/components/AppAsyncRegion.vue'
import { bindScrollbarPolicy, installScrollbarPolicy, registerScrollbarGeometry } from '@/components/scroll/installScrollbarPolicy'
import { SCROLLBAR_IDLE_MS } from '@/components/scroll/scrollbarPolicy'
import { inputModality } from '@/utils/inputModality'

const cleanups: Array<() => void> = []
afterEach(() => {
  cleanups.splice(0).reverse().forEach(stop => stop())
  document.body.replaceChildren()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function geometry(viewport: HTMLElement, x = 0, y = 300) {
  for (const [key, value] of Object.entries({ clientWidth: 200, clientHeight: 100,
    scrollWidth: 200 + x, scrollHeight: 100 + y })) {
    Object.defineProperty(viewport, key, { configurable: true, value })
  }
}
function fixture(x = 0, y = 300) {
  const root = document.createElement('div')
  root.className = 'el-scrollbar'
  root.innerHTML = '<div class="el-scrollbar__wrap"><div class="el-scrollbar__view"><button>操作</button></div></div>'
    + '<div class="el-scrollbar__bar is-vertical"><div class="el-scrollbar__thumb"></div></div>'
  document.body.append(root)
  const viewport = root.querySelector<HTMLElement>('.el-scrollbar__wrap')!
  geometry(viewport, x, y)
  cleanups.push(bindScrollbarPolicy(root)!)
  return { root, viewport, button: root.querySelector('button')!,
    visible: () => root.dataset.appScrollVisible === 'true' }
}

describe('统一滚动条显隐', () => {
  it('按方向判溢出，忽略 1px 取整误差，鼠标进出不改变尺寸和位置', () => {
    const { root, viewport, visible } = fixture(1, 0)
    expect(root.dataset.appScrollX).toBe('false')
    expect(root.dataset.appScrollY).toBe('false')
    geometry(viewport, 100, 300)
    viewport.scrollTop = 25
    root.dispatchEvent(new Event('pointerenter'))
    expect(visible()).toBe(true)
    expect(root.dataset.appScrollX).toBe('true')
    expect(root.dataset.appScrollY).toBe('true')
    root.dispatchEvent(new Event('pointerleave'))
    expect(visible()).toBe(false)
    expect(viewport.scrollTop).toBe(25)
    expect(viewport.clientWidth).toBe(200)
  })

  it('程序定位与尺寸收敛引发的滚动不显示，也不改变恢复位置', () => {
    vi.useFakeTimers()
    const { viewport, visible } = fixture()
    viewport.scrollTop = 75
    viewport.dispatchEvent(new Event('scroll'))
    expect(visible()).toBe(false)
    expect(viewport.scrollTop).toBe(75)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('滚轮产生实际滚动后保持 800ms，惯性滚动刷新期限', () => {
    vi.useFakeTimers()
    const { viewport, visible } = fixture()
    viewport.dispatchEvent(new Event('wheel', { bubbles: true }))
    expect(visible()).toBe(false)
    viewport.dispatchEvent(new Event('scroll'))
    vi.advanceTimersByTime(600)
    viewport.dispatchEvent(new Event('scroll'))
    vi.advanceTimersByTime(SCROLLBAR_IDLE_MS - 1)
    expect(visible()).toBe(true)
    vi.advanceTimersByTime(1)
    expect(visible()).toBe(false)
  })

  it('过期滚动意图不误认程序滚动，触摸滚动和键盘滚动仍显示', () => {
    vi.useFakeTimers()
    const { root, viewport, visible } = fixture()
    viewport.dispatchEvent(new Event('wheel'))
    vi.advanceTimersByTime(SCROLLBAR_IDLE_MS)
    viewport.dispatchEvent(new Event('scroll'))
    expect(visible()).toBe(false)
    viewport.dispatchEvent(new Event('touchmove'))
    viewport.dispatchEvent(new Event('scroll'))
    expect(visible()).toBe(true)
    vi.advanceTimersByTime(SCROLLBAR_IDLE_MS)
    root.dispatchEvent(new KeyboardEvent('keydown', { key: 'PageDown', bubbles: true }))
    viewport.dispatchEvent(new Event('scroll'))
    expect(visible()).toBe(true)
  })

  it('填充内容的直接块伸缩后同时更新溢出和库轨道几何', () => {
    vi.useFakeTimers()
    let resized: (() => void) | undefined
    const observed: Element[] = []
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resized = callback }
      observe(element: Element) { observed.push(element) }
      unobserve() {}
      disconnect() {}
    })
    const { root, viewport, button } = fixture(0, 0)
    const update = vi.fn()
    cleanups.push(registerScrollbarGeometry(root, update))
    expect(observed).toContain(button)
    expect(root.dataset.appScrollY).toBe('false')
    geometry(viewport, 0, 300)
    resized!()
    vi.advanceTimersByTime(20)
    expect(root.dataset.appScrollY).toBe('true')
    expect(update).toHaveBeenCalledOnce()
  })

  it('键盘焦点持续显示，鼠标点击焦点不锁定显示', async () => {
    const { root, viewport, button, visible } = fixture()
    expect(viewport.hasAttribute('tabindex')).toBe(false)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    button.focus()
    expect(visible()).toBe(true)
    button.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    expect(visible()).toBe(false)
    document.body.tabIndex = -1
    document.body.focus()
    await Promise.resolve()
    expect(visible()).toBe(false)
    root.dispatchEvent(new Event('pointerenter'))
    root.dispatchEvent(new Event('pointerleave'))
    expect(visible()).toBe(false)
  })

  it('拖出区域仍显示，取消或释放后重新判断', () => {
    const { root, visible } = fixture()
    root.querySelector('.el-scrollbar__thumb')!.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0 }))
    root.dispatchEvent(new Event('pointerleave'))
    expect(visible()).toBe(true)
    document.dispatchEvent(new Event('pointercancel'))
    expect(visible()).toBe(false)
  })

  it('触摸不产生粘滞悬停，窗口失焦清理计时器和键盘阅读意图', () => {
    vi.useFakeTimers()
    const { root, viewport, visible } = fixture()
    const enter = new Event('pointerenter')
    Object.defineProperty(enter, 'pointerType', { value: 'touch' })
    root.dispatchEvent(enter)
    expect(visible()).toBe(false)
    viewport.dispatchEvent(new Event('touchmove'))
    viewport.dispatchEvent(new Event('scroll'))
    expect(visible()).toBe(true)
    window.dispatchEvent(new Event('blur'))
    expect(visible()).toBe(false)
    expect(inputModality.isPointerInteraction()).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
    viewport.dispatchEvent(new Event('scroll'))
    expect(visible()).toBe(false)
    root.dispatchEvent(new Event('pointermove'))
    expect(visible()).toBe(true)
  })

  it('异步四态保持原有分流及命名插槽，只有内容就绪才创建 viewport', async () => {
    const loading = ref(true)
    const ready = ref(false)
    const wrapper = mount(defineComponent({
      components: { AppScrollArea },
      setup: () => ({ loading, ready, component: markRaw(AppAsyncRegion) }),
      template: '<AppScrollArea :as="component" :loading="loading" :has-content="ready">'
        + '<div>业务内容</div><template #empty><div>业务空态</div></template></AppScrollArea>',
    }), { global: { plugins: [ElementPlus] } })
    cleanups.push(() => wrapper.unmount())
    expect(wrapper.find('.el-scrollbar').exists()).toBe(false)
    expect(wrapper.find('.app-state-block--loading').exists()).toBe(true)
    loading.value = false
    await nextTick()
    expect(wrapper.text()).toContain('业务空态')
    ready.value = true
    await nextTick()
    expect(wrapper.text()).toContain('业务内容')
    expect(wrapper.find('.el-scrollbar__wrap').exists()).toBe(true)
  })

  it('缓存切换释放显隐资源，返回后保留原滚动位置并重新注册', async () => {
    const active = ref(true)
    const cached = defineComponent({ name: 'CachedScrollArea', setup: () => () => h(AppScrollArea, {}, () => h('p', '缓存内容')) })
    const app = document.createElement('main')
    document.body.append(app)
    cleanups.push(installScrollbarPolicy(app))
    const wrapper = mount(defineComponent({ setup: () => () => h(KeepAlive, {}, {
      default: () => active.value ? h(cached) : h('div', '其他页面'),
    }) }), { attachTo: app })
    cleanups.push(() => wrapper.unmount())
    await flushPromises()
    const root = wrapper.find('.el-scrollbar').element as HTMLElement
    const viewport = root.querySelector<HTMLElement>('.el-scrollbar__wrap')!
    geometry(viewport)
    viewport.scrollTop = 75
    viewport.dispatchEvent(new Event('scroll'))
    root.dispatchEvent(new Event('pointerenter'))
    active.value = false
    await flushPromises()
    expect(root.hasAttribute('data-app-scroll-managed')).toBe(false)
    active.value = true
    await flushPromises()
    expect(root.hasAttribute('data-app-scroll-managed')).toBe(true)
    viewport.dispatchEvent(new Event('scroll'))
    expect(root.dataset.appScrollVisible).toBe('false')
    expect(viewport.scrollTop).toBe(75)
  })

  it('嵌套滚动和键盘焦点只记入所属滚动实例', () => {
    const parent = fixture()
    const child = fixture()
    parent.viewport.querySelector('.el-scrollbar__view')!.append(child.root)
    child.viewport.dispatchEvent(new Event('wheel', { bubbles: true }))
    child.viewport.dispatchEvent(new Event('scroll'))
    expect(child.visible()).toBe(true)
    expect(parent.visible()).toBe(false)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab' }))
    child.button.focus()
    expect(parent.visible()).toBe(false)
  })

  it('嵌套区域触摸到边界后的滚动链显示真正滚动的外层', () => {
    const parent = fixture()
    const child = fixture()
    parent.viewport.querySelector('.el-scrollbar__view')!.append(child.root)
    child.viewport.dispatchEvent(new Event('touchmove', { bubbles: true }))
    parent.viewport.dispatchEvent(new Event('scroll'))
    expect(parent.visible()).toBe(true)
    expect(child.visible()).toBe(false)
  })

  it('动态新增自动注册，移除及卸载释放状态和监听', async () => {
    const app = document.createElement('main')
    document.body.append(app)
    const stop = installScrollbarPolicy(app)
    cleanups.push(stop)
    const wrapper = mount(ElScrollbar, { attachTo: app, slots: { default: '<div>内容</div>' } })
    cleanups.push(() => wrapper.unmount())
    await flushPromises()
    const root = wrapper.element as HTMLElement
    expect(root.hasAttribute('data-app-scroll-managed')).toBe(true)
    geometry(wrapper.vm.wrapRef!, 100, 200)
    root.dispatchEvent(new Event('pointerenter'))
    expect(root.dataset.appScrollVisible).toBe('true')
    wrapper.unmount()
    await flushPromises()
    expect(root.hasAttribute('data-app-scroll-managed')).toBe(false)
  })

  it('公共容器暴露真实 viewport，表格及候选浮层复用同一策略', async () => {
    const app = document.createElement('main')
    document.body.append(app)
    cleanups.push(installScrollbarPolicy(app))
    const wrapper = mount(defineComponent({ setup: () => () => [
      h(AppScrollArea, { ariaLabel: '内容' }, () => h('div', '滚动内容')),
      h(ElTable, { data: [{ name: '样本' }] }, () => h(ElTableColumn, { prop: 'name' })),
      h(ElSelect, { modelValue: '', teleported: false }, () => h(ElOption, { value: 'a', label: '候选' })),
    ] }), { attachTo: app })
    cleanups.push(() => wrapper.unmount())
    await flushPromises()
    const area = wrapper.findComponent(AppScrollArea)
    expect(area.vm.viewport).toBe(area.find('.el-scrollbar__wrap').element)
    await wrapper.findComponent(ElSelect).find('.el-select__wrapper').trigger('click')
    await flushPromises()
    const roots = app.querySelectorAll<HTMLElement>('.el-scrollbar')
    expect(roots.length).toBeGreaterThanOrEqual(3)
    for (const root of roots) expect(root.hasAttribute('data-app-scroll-managed')).toBe(true)
  })
})
