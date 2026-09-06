// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cloneVNode, defineComponent, h, nextTick, ref } from 'vue'
import AppRowActions from '../AppRowActions.vue'
import { useAuthStore } from '@/stores/auth'
import {
  computeRowMinimumContentWidth,
  type AppRowAction,
} from '../rowActions'
import {
  ROW_ACTION_COLUMN_WIDTH_CONTEXT,
  type RowActionColumnWidthContext,
} from '../table/rowActionColumnWidth'

const ElButtonStub = defineComponent({
  name: 'ElButton',
  props: ['type', 'disabled', 'loading', 'title'],
  emits: ['click'],
  setup(props, { slots, emit, attrs }) {
    return () => h('button', {
      ...attrs,
      class: [
        'el-button',
        attrs.class,
        props.type ? `el-button--${props.type}` : '',
        props.loading ? 'is-loading' : '',
      ],
      disabled: props.disabled || props.loading,
      title: props.title,
      onClick: (event: MouseEvent) => {
        if (!props.disabled && !props.loading) emit('click', event)
      },
    }, slots.default?.())
  },
})

const ElIconStub = defineComponent({
  name: 'ElIcon',
  setup(_props, { slots }) {
    return () => h('span', { class: 'el-icon' }, slots.default?.())
  },
})

const ElPopoverStub = defineComponent({
  name: 'ElPopover',
  props: { role: String },
  emits: ['before-enter', 'after-leave'],
  setup(props, { emit, expose, slots }) {
    const open = ref(false)
    const hide = () => {
      if (!open.value) return
      open.value = false
      emit('after-leave')
    }
    const toggle = () => {
      open.value = !open.value
      emit(open.value ? 'before-enter' : 'after-leave')
    }
    expose({ hide })
    return () => {
      const reference = (slots.reference?.() ?? []).map((vnode) => cloneVNode(vnode, {
        onClick: toggle,
        'aria-haspopup': props.role,
        'aria-expanded': String(open.value),
      }))
      return h('span', { class: 'el-popover-stub' }, [
        ...reference,
        open.value ? slots.default?.() : null,
      ])
    }
  },
})

const mountedWrappers: Array<{ unmount: () => void }> = []

/** 收集可见区域（非测量层副本）的按钮 */
function visibleButtons(wrapper: Awaited<ReturnType<typeof mountActions>>) {
  return wrapper.findAll('.app-row-actions__button').filter((button) => {
    const el = button.element as HTMLElement
    return !el.closest('.app-row-actions__measure')
  })
}

async function mountActions(actions: AppRowAction[], opts: {
  inlineLimit?: number
  role?: string
  permissions?: string[]
  testId?: string
  /** 容器可测宽度，模拟表格单元格；缺省时测量不可用，退化为数量逻辑 */
  containerWidth?: number
  /** 每个按钮的模拟宽度（按 visibleActions 顺序） */
  buttonWidths?: number[]
  /** 「更多」按钮模拟宽度 */
  moreWidth?: number
  /** 单元格横向内边距总和 */
  containerPaddingX?: number
  widthContext?: RowActionColumnWidthContext
} = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = opts.role ?? 'system'
  auth.permissions = opts.permissions ?? []

  const host = document.createElement('div')
  host.style.width = '100%'
  document.body.appendChild(host)
  const wrapper = mount(AppRowActions, {
    props: {
      actions,
      inlineLimit: opts.inlineLimit ?? 2,
      testId: opts.testId,
    },
    global: {
      plugins: [pinia],
      provide: opts.widthContext ? {
        [ROW_ACTION_COLUMN_WIDTH_CONTEXT as symbol]: opts.widthContext,
      } : undefined,
      stubs: {
        ElButton: ElButtonStub,
        ElIcon: ElIconStub,
        ElPopover: ElPopoverStub,
        ArrowDown: true,
      },
    },
    attachTo: host,
  })
  if (opts.containerWidth) {
    // 组件读取 rootEl 的父容器宽度（VTU 在 host 与根元素之间插了一个中间 wrapper）
    const rootEl = (wrapper.vm as { rootEl?: HTMLElement | null }).rootEl
    if (rootEl?.parentElement) {
      Object.defineProperty(rootEl.parentElement, 'clientWidth', {
        value: opts.containerWidth,
        configurable: true,
      })
      if (opts.containerPaddingX) {
        rootEl.parentElement.style.paddingLeft = `${opts.containerPaddingX / 2}px`
        rootEl.parentElement.style.paddingRight = `${opts.containerPaddingX / 2}px`
      }
    }
    // 测量层按钮顺序 = visibleActions 顺序，其后是「更多」按钮副本
    const measureButtons = wrapper.findAll('.app-row-actions__measure .app-row-actions__button')
    const widths = opts.buttonWidths ?? []
    measureButtons.forEach((button, index) => {
      Object.defineProperty(button.element, 'offsetWidth', {
        value: index < widths.length
          ? widths[index]
          : opts.moreWidth ?? widths[widths.length - 1],
        configurable: true,
      })
    })
    // 组件在挂载时就已测量过（拿到 jsdom 的 0 宽度），此处触发一次重测
    await wrapper.setProps({ actions: actions.map((action) => ({ ...action })) })
    await nextTick()
  }
  mountedWrappers.push(wrapper)
  return wrapper
}

describe('AppRowActions', () => {
  afterEach(() => {
    for (const wrapper of mountedWrappers.splice(0)) wrapper.unmount()
    document.body.innerHTML = ''
    vi.clearAllMocks()
  })

  it('保持行内操作单行，并把溢出和指定动作收进更多菜单', async () => {
    const remove = vi.fn()
    const wrapper = await mountActions([
      { key: 'edit', label: '编辑' },
      { key: 'reset', label: '重置密码' },
      { key: 'disable', label: '禁用', type: 'danger' },
      { key: 'delete', label: '删除', type: 'danger', placement: 'more', onClick: remove },
    ], { testId: 'user-actions' })

    const directButtons = visibleButtons(wrapper).map((button) => button.text())
    expect(wrapper.get('.app-row-actions').attributes()).toHaveProperty(
      'data-overflow-tooltip-disabled',
    )
    expect(directButtons).toEqual(['编辑', '重置密码', '更多'])
    expect(visibleButtons(wrapper)[0].classes()).toContain('is-tone-primary')
    expect(document.body.querySelector('.app-row-actions-menu')).toBeNull()

    await wrapper.find('.app-row-actions__more').trigger('click')
    await nextTick()

    expect(wrapper.get('[data-testid="user-actions-edit"]')).toBeTruthy()
    expect(wrapper.get('[data-testid="user-actions-more"]')).toBeTruthy()
    expect(wrapper.get('[data-testid="user-actions-more"]').attributes('aria-haspopup')).toBe('menu')
    expect(wrapper.get('[data-testid="user-actions-more"]').attributes('aria-expanded')).toBe('true')
    expect(document.body.querySelector('[data-testid="user-actions-menu"]')).not.toBeNull()
    const menuItems = Array.from(document.body.querySelectorAll('.app-row-actions-menu__item'))
    expect(menuItems.map((item) => item.textContent?.trim())).toEqual(['禁用', '删除'])

    window.dispatchEvent(new Event('scroll'))
    await nextTick()
    expect(document.body.querySelector('[data-testid="user-actions-menu"]')).not.toBeNull()

    const deleteItem = menuItems.find((item) => item.textContent?.trim() === '删除') as HTMLButtonElement
    deleteItem.click()
    await nextTick()
    expect(remove).toHaveBeenCalledTimes(1)
    expect(document.body.querySelector('[data-testid="user-actions-menu"]')).toBeNull()
  })

  it('首个未指定语义色的行内高频动作使用主色，后续普通动作保持弱化', async () => {
    const wrapper = await mountActions([
      { key: 'view', label: '查看' },
      { key: 'open', label: '打开' },
    ], { inlineLimit: 2 })

    const buttons = visibleButtons(wrapper)
    expect(buttons[0].classes()).toContain('is-tone-primary')
    expect(buttons[1].classes()).toContain('is-tone-default')
  })

  it('按权限过滤不可见动作，口径与 v-permission 保持一致', async () => {
    const wrapper = await mountActions([
      { key: 'edit', label: '编辑', permission: 'user:update' },
      { key: 'delete', label: '删除', permission: 'user:delete', placement: 'more' },
    ], { role: 'normal', permissions: ['user:update'] })

    // 只断言可见按钮（测量层副本是 aria-hidden 的）
    const visibleText = visibleButtons(wrapper)
      .map((button) => button.text())
      .join('')
    expect(visibleText).toContain('编辑')
    expect(visibleText).not.toContain('删除')
    expect(visibleText).not.toContain('更多')
  })

  it('禁用和加载中的动作不会触发回调', async () => {
    const disabled = vi.fn()
    const loading = vi.fn()
    const wrapper = await mountActions([
      { key: 'disabled', label: '禁用态', disabled: true, onClick: disabled },
      { key: 'loading', label: '加载态', loading: true, onClick: loading },
    ], { inlineLimit: 2 })

    const buttons = visibleButtons(wrapper)
    for (const button of buttons) {
      await button.trigger('click')
    }

    expect(disabled).not.toHaveBeenCalled()
    expect(loading).not.toHaveBeenCalled()
  })

  it('更多菜单使用 Element Plus 命令按钮并展示可见 loading 状态', async () => {
    const loading = vi.fn()
    const wrapper = await mountActions([
      { key: 'edit', label: '编辑' },
      { key: 'sync', label: '同步中', loading: true, placement: 'more', onClick: loading },
    ], { inlineLimit: 1, testId: 'quality-actions' })

    await wrapper.get('[data-testid="quality-actions-more"]').trigger('click')
    await nextTick()

    const loadingItem = document.body.querySelector(
      '[data-testid="quality-actions-sync"]',
    ) as HTMLButtonElement
    expect(loadingItem.classList).toContain('el-button')
    expect(loadingItem.classList).toContain('is-loading')
    expect(loadingItem.disabled).toBe(true)
    loadingItem.click()
    expect(loading).not.toHaveBeenCalled()
  })

  it('宽度放不下时自动把第三个按钮收进更多（不再硬截断）', async () => {
    const wrapper = await mountActions([
      { key: 'edit', label: '编辑', testId: 'w-edit' },
      { key: 'reset', label: '重置密码', testId: 'w-reset' },
      { key: 'delete', label: '删除', testId: 'w-delete' },
    ], {
      inlineLimit: 3,
      containerWidth: 140,
      buttonWidths: [60, 60, 60],
      moreWidth: 64,
      testId: 'w-actions',
    })
    await nextTick()

    const directButtons = visibleButtons(wrapper).map((button) => button.text())
    // 60 + 8 + 64(更多) = 132 <= 140；第三个按钮放不下 → 收进更多
    expect(directButtons).toEqual(['编辑', '更多'])
    expect(wrapper.find('[data-testid="w-actions-delete"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="w-actions-more"]').exists()).toBe(true)

    await wrapper.find('.app-row-actions__more').trigger('click')
    await nextTick()
    const menuItems = Array.from(document.body.querySelectorAll('.app-row-actions-menu__item'))
    expect(menuItems.map((item) => item.textContent?.trim())).toEqual(['重置密码', '删除'])
  })

  it('宽度足够时不再出现更多（即使数量超过默认上限）', async () => {
    const wrapper = await mountActions([
      { key: 'edit', label: '编辑', testId: 't-edit' },
      { key: 'reset', label: '重置密码', testId: 't-reset' },
      { key: 'delete', label: '删除', testId: 't-delete' },
    ], {
      inlineLimit: 3,
      containerWidth: 400,
      buttonWidths: [60, 60, 60],
      moreWidth: 64,
      testId: 't-actions',
    })
    await nextTick()

    const directButtons = visibleButtons(wrapper).map((button) => button.text())
    // 三个按钮 196px < 400px，无需更多
    expect(directButtons).toEqual(['编辑', '重置密码', '删除'])
    expect(wrapper.find('[data-testid="t-actions-more"]').exists()).toBe(false)
  })

  it('单动作完整显示，多动作从两直接动作或首动作加更多中选择最低宽度', () => {
    expect(computeRowMinimumContentWidth([
      { key: 'logs', label: '日志', measured: 40, measuredOk: true },
    ], 2, 56)).toBe(40)
    expect(computeRowMinimumContentWidth([
      { key: 'retry', label: '重试未完成项', measured: 92, measuredOk: true },
      { key: 'logs', label: '日志', measured: 40, measuredOk: true },
    ], 2, 56)).toBe(140)
    expect(computeRowMinimumContentWidth([
      { key: 'retry', label: '重试未完成项', measured: 92, measuredOk: true },
      { key: 'logs', label: '日志', measured: 40, measuredOk: true },
      { key: 'delete', label: '删除', measured: 40, measuredOk: true },
    ], 2, 56)).toBe(156)
    expect(computeRowMinimumContentWidth([
      { key: 'delete', label: '删除', placement: 'more', measured: 40, measuredOk: true },
    ], 2, 56)).toBe(56)
  })

  it('向所属操作列上报含单元格内边距的最低可用宽度', async () => {
    const widthContext: RowActionColumnWidthContext = {
      setMinimumWidth: vi.fn(),
      removeMinimumWidth: vi.fn(),
    }
    const wrapper = await mountActions([
      { key: 'retry', label: '重试未完成项' },
      { key: 'logs', label: '日志' },
    ], {
      inlineLimit: 2,
      containerWidth: 144,
      buttonWidths: [92, 40],
      moreWidth: 56,
      containerPaddingX: 24,
      widthContext,
    })

    expect(widthContext.setMinimumWidth).toHaveBeenLastCalledWith(expect.any(Symbol), 164)
    wrapper.unmount()
    expect(widthContext.removeMinimumWidth).toHaveBeenCalledWith(expect.any(Symbol))
  })
})
