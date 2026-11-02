// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import AppPagination from '@/components/AppPagination.vue'

let availableWidth = 700
let resizeCallback: ResizeObserverCallback | undefined
let fullLayoutScrollWidth = 0
const originalClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth')
const originalScrollWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollWidth')

const ElPaginationStub = defineComponent({
  name: 'ElPagination',
  props: {
    currentPage: { type: Number, required: true },
    pageSize: { type: Number, required: true },
    pageSizes: { type: Array, required: true },
    pagerCount: { type: Number, required: true },
    total: { type: Number, required: true },
    size: { type: String, required: true },
    layout: { type: String, required: true },
  },
  emits: ['current-change', 'size-change'],
  setup(props, { emit, slots }) {
    return () => h('div', {
      class: 'el-pagination',
      'data-layout': props.layout,
      'data-pager-count': String(props.pagerCount),
      'data-size': props.size,
    }, [
      props.layout.includes('slot') ? slots.default?.() : null,
      h('button', { class: 'page-change', onClick: () => emit('current-change', 2) }, 'page'),
      h('button', { class: 'size-change', onClick: () => emit('size-change', 100) }, 'size'),
    ])
  },
})

function mountPagination() {
  return mount(AppPagination, {
    props: { currentPage: 1, pageSize: 50, total: 5018 },
    global: { stubs: { ElPagination: ElPaginationStub } },
  })
}

beforeEach(() => {
  availableWidth = 700
  resizeCallback = undefined
  fullLayoutScrollWidth = 0
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    get: () => availableWidth,
  })
  Object.defineProperty(HTMLElement.prototype, 'scrollWidth', {
    configurable: true,
    get() {
      if (
        this.classList.contains('el-pagination')
        && this.getAttribute('data-layout') === 'slot, sizes, prev, pager, next'
      ) {
        return fullLayoutScrollWidth
      }
      return 0
    },
  })
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: ResizeObserverCallback) { resizeCallback = callback }
    observe() {}
    disconnect() {}
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  if (originalClientWidth) {
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', originalClientWidth)
  } else {
    Reflect.deleteProperty(HTMLElement.prototype, 'clientWidth')
  }
  if (originalScrollWidth) {
    Object.defineProperty(HTMLElement.prototype, 'scrollWidth', originalScrollWidth)
  } else {
    Reflect.deleteProperty(HTMLElement.prototype, 'scrollWidth')
  }
})

describe('AppPagination', () => {
  it('宽容器显示总数、每页条数和完整页码导航', async () => {
    const wrapper = mountPagination()
    await nextTick()

    const pagination = wrapper.get('.el-pagination')
    expect(pagination.attributes('data-layout')).toBe('slot, sizes, prev, pager, next')
    expect(pagination.attributes('data-pager-count')).toBe('7')
    expect(wrapper.text()).toContain('共 5,018 条')
    expect(pagination.attributes('data-size')).toBe('default')
  })

  it('中等容器隐藏每页条数并保留总数和主要翻页能力', async () => {
    availableWidth = 500
    const wrapper = mountPagination()
    await nextTick()

    const pagination = wrapper.get('.el-pagination')
    expect(pagination.attributes('data-layout')).toBe('slot, prev, pager, next')
    expect(pagination.attributes('data-pager-count')).toBe('5')
    expect(pagination.attributes('data-size')).toBe('small')
  })

  it('窄容器降为紧凑页码导航，并随容器变化恢复完整布局', async () => {
    availableWidth = 360
    const wrapper = mountPagination()
    await nextTick()

    expect(wrapper.get('.el-pagination').attributes('data-layout')).toBe('prev, pager, next')

    availableWidth = 700
    resizeCallback?.([], {} as ResizeObserver)
    await nextTick()
    expect(wrapper.get('.el-pagination').attributes('data-layout')).toBe('slot, sizes, prev, pager, next')
  })

  it('内容长度超过容器时继续降级，不只依赖固定断点猜测宽度', async () => {
    fullLayoutScrollWidth = 760
    const wrapper = mountPagination()
    await nextTick()
    await nextTick()

    expect(wrapper.get('.el-pagination').attributes('data-layout')).toBe('slot, prev, pager, next')
    expect(wrapper.get('.el-pagination').attributes('data-pager-count')).toBe('5')
  })

  it('继续向调用方透传换页和每页条数事件', async () => {
    const wrapper = mountPagination()
    await wrapper.get('.page-change').trigger('click')
    await wrapper.get('.size-change').trigger('click')

    expect(wrapper.emitted('current-change')?.[0]).toEqual([2])
    expect(wrapper.emitted('size-change')?.[0]).toEqual([100])
  })
})
