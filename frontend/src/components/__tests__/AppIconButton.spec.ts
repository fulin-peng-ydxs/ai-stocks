// @vitest-environment jsdom
import { defineComponent, nextTick } from 'vue'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import AppHoverInfo from '../AppHoverInfo'
import { afterEach, describe, expect, it } from 'vitest'
import AppIconButton from '../AppIconButton.vue'

enableAutoUnmount(afterEach)

describe('AppIconButton', () => {
  it('为纯图标操作提供统一尺寸、语义标签、默认提示和状态样式', async () => {
    const wrapper = mount(AppIconButton, {
      props: { label: '刷新状态', size: 'sm', variant: 'soft', tone: 'primary' },
      slots: { default: '<svg data-test="icon" />' },
    })

    const button = wrapper.get('button')
    expect(button.attributes('type')).toBe('button')
    expect(button.attributes('aria-label')).toBe('刷新状态')
    expect(button.attributes('title')).toBeUndefined()
    await nextTick()
    expect(wrapper.getComponent(AppHoverInfo).vm.$attrs.content).toBe('刷新状态')
    expect(button.classes()).toEqual(expect.arrayContaining(['is-sm', 'is-soft', 'is-primary']))
    expect(wrapper.find('[data-test="icon"]').exists()).toBe(true)
  })

  it('默认提示随动作名称更新，覆盖文案可独立更新并恢复默认', async () => {
    const wrapper = mount(AppIconButton, { props: { label: '加入自选：股票甲' } })
    await nextTick()
    await wrapper.setProps({ label: '移出自选：股票甲' })
    expect(wrapper.getComponent(AppHoverInfo).vm.$attrs.content).toBe('移出自选：股票甲')
    await wrapper.setProps({ tooltip: '从当前自选分组移除此股票' })
    await wrapper.setProps({ label: '移出自选：股票乙' })
    expect(wrapper.getComponent(AppHoverInfo).vm.$attrs.content).toBe('从当前自选分组移除此股票')
    await wrapper.setProps({ tooltip: undefined })
    expect(wrapper.getComponent(AppHoverInfo).vm.$attrs.content).toBe('移出自选：股票乙')
  })

  it('仅 false 明确关闭提示，空字符串仍回退用途名称', async () => {
    const wrapper = mount(AppIconButton, { props: { label: '清空筛选', tooltip: false } })
    await nextTick()
    expect(wrapper.findComponent(AppHoverInfo).exists()).toBe(false)
    expect(wrapper.get('button').attributes('aria-label')).toBe('清空筛选')
    await wrapper.setProps({ tooltip: '  ' })
    expect(wrapper.getComponent(AppHoverInfo).vm.$attrs.content).toBe('清空筛选')
    await wrapper.setProps({ tooltip: false })
    expect(wrapper.findComponent(AppHoverInfo).exists()).toBe(false)
  })

  it('禁用与加载期间停止提示，恢复可用后保留默认说明', async () => {
    const wrapper = mount(AppIconButton, { props: { label: '刷新行情' } })
    await nextTick()
    expect(wrapper.getComponent(AppHoverInfo).props('disabled')).toBe(false)
    await wrapper.setProps({ disabled: true })
    expect(wrapper.getComponent(AppHoverInfo).props('disabled')).toBe(true)
    await wrapper.setProps({ disabled: false, loading: true })
    expect(wrapper.getComponent(AppHoverInfo).props('disabled')).toBe(true)
    await wrapper.setProps({ loading: false })
    expect(wrapper.getComponent(AppHoverInfo).props('disabled')).toBe(false)
    expect(wrapper.getComponent(AppHoverInfo).vm.$attrs.content).toBe('刷新行情')
  })

  it('透传点击事件，禁用态由原生 button 阻止触发', async () => {
    const wrapper = mount(AppIconButton, { props: { label: '关闭' } })
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('click')).toHaveLength(1)

    await wrapper.setProps({ disabled: true })
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('click')).toHaveLength(1)
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
  })

  it('统一承载纯图标异步 loading，阻止重复点击但不复用禁用灰态表达进度', async () => {
    const wrapper = mount(AppIconButton, {
      props: { label: '同步预设', loading: true },
      slots: { default: '<svg data-test="refresh" />' },
    })

    const button = wrapper.get('button')
    expect(button.attributes('disabled')).toBeDefined()
    expect(button.attributes('aria-busy')).toBe('true')
    expect(button.classes()).toContain('is-loading')
    expect(wrapper.find('.app-icon-button__loading').exists()).toBe(true)
    expect(wrapper.find('[data-test="refresh"]').exists()).toBe(false)

    await button.trigger('click')
    expect(wrapper.emitted('click')).toBeUndefined()
  })

  it('显式说明复用 AppHoverInfo，保留 button 根节点', async () => {
    const wrapper = mount(AppIconButton, {
      props: { label: '同步预设', tooltip: '同步共享配置的最新版本' },
    })

    expect(wrapper.get('button').attributes('aria-label')).toBe('同步预设')
    expect(wrapper.get('button').attributes('title')).toBeUndefined()
    expect(wrapper.element.tagName).toBe('BUTTON')
    await nextTick()
    expect(wrapper.findComponent(AppHoverInfo).vm.$attrs.content).toBe('同步共享配置的最新版本')
    wrapper.unmount()
  })
  it('默认提示不改变权限指令的真实 button 目标', async () => {
    let target: HTMLElement | undefined
    const host = defineComponent({ components: { AppIconButton }, template: '<AppIconButton v-permission label="新增节点" />' })
    const wrapper = mount(host, { global: { directives: { permission: { mounted: (el: HTMLElement) => { target = el; el.style.display = 'none' } } } } })
    await nextTick()
    expect(target?.tagName).toBe('BUTTON')
    expect(wrapper.get('button').element).toBe(target)
    expect(target?.style.display).toBe('none')
    wrapper.unmount()
  })

})
