// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, nextTick, ref } from 'vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
import SettingsGroup from '@/components/SettingsGroup.vue'
import * as itemLayout from '@/composables/settingItemLayout'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('PageSettingItem', () => {
  it('默认使用堆叠布局并统一渲染事项名、控件和辅助说明', () => {
    const wrapper = mount(PageSettingItem, {
      props: { label: '默认视图' },
      slots: { default: '<button>全市场</button>', help: '下次进入页面时生效' },
    })

    expect(wrapper.classes()).toContain('is-stacked')
    expect(wrapper.find('.psi-label').text()).toBe('默认视图')
    expect(wrapper.find('.psi-control').text()).toBe('全市场')
    expect(wrapper.find('.psi-help').text()).toBe('下次进入页面时生效')
  })

  it('行内布局和 label 插槽支持开关类事项', () => {
    const wrapper = mount(PageSettingItem, {
      props: { layout: 'inline' },
      slots: { label: '排除 ST', default: '<input type="checkbox" />' },
    })

    expect(wrapper.classes()).toContain('is-inline')
    expect(wrapper.find('.psi-label').text()).toBe('排除 ST')
    expect(wrapper.find('input').exists()).toBe(true)
  })

  it('容量不足统一兄弟项，开关和嵌套子组独立；恢复、移除及卸载后清理状态', async () => {
    let width = 320
    const callbacks: ResizeObserverCallback[] = []
    const disconnect = vi.fn()
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: ResizeObserverCallback) { callbacks.push(callback) }
      observe() {}
      disconnect = disconnect
    })
    const frames: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { frames.push(callback); return frames.length })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => width)
    vi.spyOn(itemLayout, 'measureSettingItemInlineWidth').mockImplementation(element => (
      element.dataset.testid === 'wide' ? 240 : element.dataset.testid === 'toggle' ? 280 : 60
    ))
    const Host = defineComponent({
      components: { SettingsGroup, PageSettingItem },
      setup: () => ({ showStacked: ref(true) }),
      template: `<SettingsGroup title="父组" :collapsible="false">
        <PageSettingItem data-testid="wide" label="长标题" layout="inline"><input /></PageSettingItem>
        <PageSettingItem data-testid="sibling" label="数字" layout="inline"><input /></PageSettingItem>
        <PageSettingItem v-if="showStacked" data-testid="stacked" label="枚举"><input /></PageSettingItem>
        <PageSettingItem data-testid="toggle" label="开关" layout="inline"><input type="checkbox" /></PageSettingItem>
        <SettingsGroup title="子组" :collapsible="false">
          <PageSettingItem data-testid="nested" label="数值" layout="inline"><input /></PageSettingItem>
        </SettingsGroup>
      </SettingsGroup>`,
    })
    const wrapper = mount(Host, { global: { stubs: {
      ElCollapseTransition: { template: '<div><slot/></div>' }, ElIcon: true, AppIconButton: true,
    } } })
    const item = (id: string) => wrapper.get(`[data-testid="${id}"]`)
    const flush = async () => {
      await nextTick()
      frames.splice(0).forEach(callback => callback(0))
      await nextTick()
    }
    await flush()
    expect(item('wide').classes()).toContain('is-stacked')
    expect(item('sibling').classes()).toContain('is-stacked')
    expect(item('toggle').classes()).toContain('is-inline')
    expect(item('nested').classes()).toContain('is-inline')
    wrapper.vm.showStacked = false
    await flush()
    expect(item('wide').classes()).toContain('is-inline')
    const originalInput = item('wide').get('input').element
    originalInput.value = '123'
    width = 260
    callbacks.forEach(callback => callback([], {} as ResizeObserver))
    await flush()
    expect(item('toggle').classes()).toContain('is-stacked')
    expect(item('wide').classes()).toContain('is-inline')
    expect(item('sibling').classes()).toContain('is-inline')
    width = 200
    callbacks.forEach(callback => callback([], {} as ResizeObserver))
    await flush()
    expect(item('wide').classes()).toContain('is-stacked')
    expect(item('sibling').classes()).toContain('is-stacked')
    expect(item('nested').classes()).toContain('is-inline')
    // 重复观察同一容量不会因已变成上下排版而反复恢复同行。
    await flush()
    expect(item('wide').classes()).toContain('is-stacked')
    width = 400
    callbacks.forEach(callback => callback([], {} as ResizeObserver))
    await flush()
    expect(item('wide').classes()).toContain('is-inline')
    expect(item('sibling').classes()).toContain('is-inline')
    expect(item('wide').get('input').element).toBe(originalInput)
    expect(originalInput.value).toBe('123')
    wrapper.unmount()
    expect(disconnect).toHaveBeenCalled()
  })
})
