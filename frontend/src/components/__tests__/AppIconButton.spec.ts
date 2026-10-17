// @vitest-environment jsdom
import { defineComponent, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import AppHoverInfo from '../AppHoverInfo'
import { describe, expect, it } from 'vitest'
import AppIconButton from '../AppIconButton.vue'

describe('AppIconButton', () => {
  it('为纯图标操作提供统一尺寸、语义标签和状态样式', () => {
    const wrapper = mount(AppIconButton, {
      props: { label: '刷新状态', size: 'sm', variant: 'soft', tone: 'primary' },
      slots: { default: '<svg data-test="icon" />' },
    })

    const button = wrapper.get('button')
    expect(button.attributes('type')).toBe('button')
    expect(button.attributes('aria-label')).toBe('刷新状态')
    expect(button.attributes('title')).toBeUndefined()
    expect(wrapper.findComponent(AppHoverInfo).exists()).toBe(false)
    expect(button.classes()).toEqual(expect.arrayContaining(['is-sm', 'is-soft', 'is-primary']))
    expect(wrapper.find('[data-test="icon"]').exists()).toBe(true)
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
  it('显式提示不改变权限指令的真实 button 目标', async () => {
    let target: HTMLElement | undefined
    const host = defineComponent({ components: { AppIconButton }, template: '<AppIconButton v-permission label="新增节点" tooltip="新增根节点" />' })
    const wrapper = mount(host, { global: { directives: { permission: { mounted: (el: HTMLElement) => { target = el; el.style.display = 'none' } } } } })
    await nextTick()
    expect(target?.tagName).toBe('BUTTON')
    expect(wrapper.get('button').element).toBe(target)
    expect(target?.style.display).toBe('none')
    wrapper.unmount()
  })

})
