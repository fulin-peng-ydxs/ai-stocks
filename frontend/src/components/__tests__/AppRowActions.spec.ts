// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import AppRowActions from '../AppRowActions.vue'
import { useAuthStore } from '@/stores/auth'
import type { AppRowAction } from '../rowActions'

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

const mountedWrappers: Array<{ unmount: () => void }> = []

function mountActions(actions: AppRowAction[], opts: {
  inlineLimit?: number
  role?: string
  permissions?: string[]
  testId?: string
} = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = opts.role ?? 'system'
  auth.permissions = opts.permissions ?? []

  const wrapper = mount(AppRowActions, {
    props: {
      actions,
      inlineLimit: opts.inlineLimit ?? 2,
      testId: opts.testId,
    },
    global: {
      plugins: [pinia],
      stubs: {
        ElButton: ElButtonStub,
        ElIcon: ElIconStub,
        ArrowDown: true,
      },
    },
    attachTo: document.body,
  })
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
    const wrapper = mountActions([
      { key: 'edit', label: '编辑' },
      { key: 'reset', label: '重置密码' },
      { key: 'disable', label: '禁用', type: 'danger' },
      { key: 'delete', label: '删除', type: 'danger', placement: 'more', onClick: remove },
    ], { testId: 'user-actions' })

    const directButtons = wrapper.findAll('.app-row-actions__button').map((button) => button.text())
    expect(directButtons).toEqual(['编辑', '重置密码', '更多'])
    expect(wrapper.findAll('.app-row-actions__button')[0].classes()).toContain('is-tone-primary')
    expect(document.body.querySelector('.app-row-actions-menu')).toBeNull()

    await wrapper.find('.app-row-actions__more').trigger('click')
    await nextTick()

    expect(wrapper.get('[data-testid="user-actions-edit"]')).toBeTruthy()
    expect(wrapper.get('[data-testid="user-actions-more"]')).toBeTruthy()
    expect(document.body.querySelector('[data-testid="user-actions-menu"]')).not.toBeNull()
    const menuItems = Array.from(document.body.querySelectorAll('.app-row-actions-menu__item'))
    expect(menuItems.map((item) => item.textContent?.trim())).toEqual(['禁用', '删除'])

    window.dispatchEvent(new Event('scroll'))
    await nextTick()
    expect(document.body.querySelector('[data-testid="user-actions-menu"]')).not.toBeNull()

    const deleteItem = menuItems.find((item) => item.textContent?.trim() === '删除') as HTMLButtonElement
    deleteItem.click()
    expect(remove).toHaveBeenCalledTimes(1)
  })

  it('首个未指定语义色的行内高频动作使用主色，后续普通动作保持弱化', () => {
    const wrapper = mountActions([
      { key: 'view', label: '查看' },
      { key: 'open', label: '打开' },
    ], { inlineLimit: 2 })

    const buttons = wrapper.findAll('.app-row-actions__button')
    expect(buttons[0].classes()).toContain('is-tone-primary')
    expect(buttons[1].classes()).toContain('is-tone-default')
  })

  it('按权限过滤不可见动作，口径与 v-permission 保持一致', () => {
    const wrapper = mountActions([
      { key: 'edit', label: '编辑', permission: 'user:update' },
      { key: 'delete', label: '删除', permission: 'user:delete', placement: 'more' },
    ], { role: 'normal', permissions: ['user:update'] })

    expect(wrapper.text()).toContain('编辑')
    expect(wrapper.text()).not.toContain('删除')
    expect(wrapper.text()).not.toContain('更多')
  })

  it('禁用和加载中的动作不会触发回调', async () => {
    const disabled = vi.fn()
    const loading = vi.fn()
    const wrapper = mountActions([
      { key: 'disabled', label: '禁用态', disabled: true, onClick: disabled },
      { key: 'loading', label: '加载态', loading: true, onClick: loading },
    ], { inlineLimit: 2 })

    for (const button of wrapper.findAll('.app-row-actions__button')) {
      await button.trigger('click')
    }

    expect(disabled).not.toHaveBeenCalled()
    expect(loading).not.toHaveBeenCalled()
  })

  it('更多菜单使用 Element Plus 命令按钮并展示可见 loading 状态', async () => {
    const loading = vi.fn()
    const wrapper = mountActions([
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
})
