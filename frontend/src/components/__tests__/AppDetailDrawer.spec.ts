// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AppDetailDrawer from '../AppDetailDrawer.vue'

const stubs = {
  PageDrawer: {
    name: 'PageDrawer',
    props: ['bodyLayout', 'bodyScroll'],
    template: '<section><slot/><slot name="footer"/></section>',
  },
  AppStateBlock: {
    name: 'AppStateBlock',
    props: ['state', 'retry'],
    emits: ['retry'],
    template: '<div><button v-if="retry" @click="$emit(\'retry\')">重试</button></div>',
  },
}

describe('详情抽屉正文布局', () => {
  it('普通详情保留流式正文和外层滚动', () => {
    const wrapper = mount(AppDetailDrawer, {
      props: { modelValue: true, title: '详情' },
      slots: { default: '<div>详情正文</div>' }, global: { stubs },
    })
    const surface = wrapper.getComponent({ name: 'PageDrawer' })
    expect(surface.props('bodyLayout')).toBe('flow')
    expect(surface.props('bodyScroll')).toBe(true)
    expect(wrapper.get('.app-detail-drawer__body').classes()).not.toContain('is-fill')
    wrapper.unmount()
  })

  it('单表填满模式向共享外壳传递滚动归属，错误态隐藏原内容并重试', async () => {
    const wrapper = mount(AppDetailDrawer, {
      props: { modelValue: true, title: '触发记录', bodyLayout: 'fill', bodyScroll: false },
      slots: { default: '<div class="records">记录列表</div>' }, global: { stubs },
    })
    const surface = wrapper.getComponent({ name: 'PageDrawer' })
    expect(surface.props('bodyLayout')).toBe('fill')
    expect(surface.props('bodyScroll')).toBe(false)
    expect(wrapper.get('.app-detail-drawer__body').classes()).toContain('is-fill')
    await wrapper.setProps({ state: 'error', retry: true })
    expect(wrapper.find('.records').exists()).toBe(false)
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
    wrapper.unmount()
  })
})
