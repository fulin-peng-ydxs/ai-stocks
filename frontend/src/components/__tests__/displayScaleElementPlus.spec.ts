// @vitest-environment jsdom
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { ElTable, ElTableColumn, ElScrollbar, ElTree, ElTabs, ElTabPane } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const wrappers: ReturnType<typeof mount>[] = []
let scale = 1
const resizeCallbacks: Array<() => void> = []
function dimensions(el: HTMLElement) {
  const thumb = el.classList.contains('el-scrollbar__thumb')
  const bar = el.classList.contains('el-scrollbar__bar')
  const wrap = el.classList.contains('el-scrollbar__wrap')
  return {
    width: el.tagName === 'TH' ? 200 : el.classList.contains('el-tabs__nav') ? 1200
      : el.classList.contains('el-tabs__nav-scroll') ? 400 : 1000,
    height: thumb ? Number.parseFloat(el.style.height) || 20 : bar ? 196 : wrap ? 200 : 40,
  }
}

beforeEach(() => {
  resizeCallbacks.length = 0
  vi.stubGlobal('ResizeObserver', class {
    constructor(private callback: (entries: unknown[]) => void) {}
    observe(target: HTMLElement) {
      resizeCallbacks.push(() => this.callback([{ target, contentRect: target.getBoundingClientRect() }]))
    }
    unobserve() {}
    disconnect() {}
  })
  for (const key of ['offsetWidth', 'clientWidth'] as const) {
    vi.spyOn(HTMLElement.prototype, key, 'get').mockImplementation(function (this: HTMLElement) {
      return dimensions(this).width
    })
  }
  for (const key of ['offsetHeight', 'clientHeight'] as const) {
    vi.spyOn(HTMLElement.prototype, key, 'get').mockImplementation(function (this: HTMLElement) {
      return dimensions(this).height
    })
  }
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(1000)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const { width, height } = dimensions(this)
    return new DOMRect(100, 100, width * scale, height * scale)
  })
})
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.restoreAllMocks(); vi.unstubAllGlobals()
})
function mouse(target: EventTarget, type: string, x: number, y = 110) {
  target.dispatchEvent(new MouseEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0 }))
}

describe('Element Plus 实际交互的缩放兼容', () => {
  it.each([0.5, 0.8, 1, 1.25, 1.5])('比例 %s：表头原地松开不改变列宽，拖动按布局像素计量', async (value) => {
    scale = value
    const wrapper = mount(defineComponent({
      setup: () => () => h(ElTable, { data: [{ name: '样本' }], border: true }, () => [
        h(ElTableColumn, { prop: 'name', label: '名称', width: 200 }),
        h(ElTableColumn, { prop: 'name', label: '第二列', width: 300 }),
      ]),
    }), { attachTo: document.body })
    wrappers.push(wrapper)
    await flushPromises()
    const header = wrapper.find('th').element
    const start = 100 + 200 * scale - 2
    mouse(header, 'mousemove', start)
    mouse(header, 'mousedown', start)
    mouse(document, 'mouseup', start)
    await nextTick()
    const table = wrapper.findComponent({ name: 'ElTable' })
    expect(table.emitted('header-dragend')?.[0]?.[0]).toBe(200)
    mouse(header, 'mousemove', start)
    mouse(header, 'mousedown', start)
    mouse(document, 'mousemove', start + 40 * scale)
    mouse(document, 'mouseup', start + 40 * scale)
    await nextTick()
    expect(table.emitted('header-dragend')?.[1]?.[0]).toBe(240)
  })

  it.each([0.5, 0.8, 1, 1.25, 1.5])('比例 %s：滚动条拖动与轨道点击得到同一布局位置', async (value) => {
    scale = value
    const wrapper = mount(ElScrollbar, { props: { height: '200px', always: true },
      slots: { default: '<div>长内容</div>' }, attachTo: document.body })
    wrappers.push(wrapper)
    await flushPromises()
    wrapper.vm.update()
    await nextTick()
    const bar = wrapper.find('.el-scrollbar__bar.is-vertical').element as HTMLElement
    const thumb = bar.querySelector('.el-scrollbar__thumb') as HTMLElement
    const wrap = wrapper.find('.el-scrollbar__wrap').element as HTMLElement
    mouse(thumb, 'mousedown', 110, 100 + 5 * scale)
    mouse(document, 'mousemove', 110, 100 + 45 * scale)
    mouse(document, 'mouseup', 110, 100 + 45 * scale)
    const dragged = wrap.scrollTop
    expect(dragged).toBeGreaterThan(0)
    wrap.scrollTop = 0
    mouse(bar, 'mousedown', 110, 100 + (40 + thumb.offsetHeight / 2) * scale)
    expect(wrap.scrollTop).toBeCloseTo(dragged, 5)
    expect(dragged).toBeCloseTo(40 / (196 - thumb.offsetHeight) * (1000 - 196), 5)
  })
  it.each([0.5, 1, 1.5])('比例 %s：溢出标签页按布局宽度翻页', async (value) => {
    scale = value
    const wrapper = mount(ElTabs, { props: { modelValue: '1' }, slots: {
      default: () => Array.from({ length: 12 }, (_, i) => h(ElTabPane, {
        name: String(i + 1), label: `页面 ${i + 1}`,
      })),
    }, attachTo: document.body })
    wrappers.push(wrapper)
    await flushPromises()
    resizeCallbacks.forEach((callback) => callback())
    await new Promise(requestAnimationFrame)
    await nextTick()
    await wrapper.get('.el-tabs__nav-next').trigger('click')
    expect((wrapper.get('.el-tabs__nav').element as HTMLElement).style.transform).toBe('translateX(-400px)')
  })

  it.each([0.5, 1, 1.5])('比例 %s：树节点拖放指示线回到树内布局坐标', async (value) => {
    scale = value
    const wrapper = mount(ElTree, { props: { draggable: true, data: [
      { id: 1, label: '目录一' }, { id: 2, label: '目录二' }, { id: 3, label: '目录三' },
    ], nodeKey: 'id' }, attachTo: document.body })
    wrappers.push(wrapper)
    await flushPromises()
    const tree = wrapper.element as HTMLElement
    Object.defineProperties(tree, { offsetWidth: { value: 300 }, offsetHeight: { value: 104 } })
    vi.spyOn(tree, 'getBoundingClientRect').mockReturnValue(new DOMRect(100, 100, 300 * scale, 104 * scale))
    const nodes = wrapper.findAll('.el-tree-node')
    const content = nodes[2].get('.el-tree-node__content').element
    const icon = nodes[2].get('.el-tree-node__expand-icon').element
    vi.spyOn(content, 'getBoundingClientRect').mockReturnValue(new DOMRect(100, 100 + 52 * scale, 300 * scale, 26 * scale))
    vi.spyOn(icon, 'getBoundingClientRect').mockReturnValue(new DOMRect(100, 100 + 52 * scale, 18 * scale, 26 * scale))
    const drag = (target: Element, type: string, y: number) => {
      const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientY: y })
      Object.defineProperty(event, 'dataTransfer', { value: { setData: vi.fn(), setDragImage: vi.fn() } })
      target.dispatchEvent(event)
    }
    drag(nodes[0].element, 'dragstart', 100 + scale)
    drag(nodes[2].element, 'dragover', 100 + 53 * scale)
    await nextTick()
    const indicator = wrapper.get('.el-tree__drop-indicator').element as HTMLElement
    expect(indicator.style.top).toBe('52px')
    expect(indicator.style.left).toBe('18px')
  })

})
