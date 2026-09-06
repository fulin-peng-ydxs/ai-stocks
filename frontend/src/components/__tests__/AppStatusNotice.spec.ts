// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import appStatusNoticeSource from '@/components/AppStatusNotice.vue?raw'

describe('AppStatusNotice', () => {
  it('以持久状态语义展示标题、说明和文字动作', async () => {
    const wrapper = mount(AppStatusNotice, {
      props: {
        tone: 'warning',
        size: 'compact',
        title: '数据暂未更新',
        description: '当前继续使用缓存数据',
        actionText: '重新加载',
      },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.attributes('role')).toBe('status')
    expect(wrapper.text()).toContain('当前继续使用缓存数据')
    const action = wrapper.get('button')
    expect(action.classes()).toContain('is-link')
    await action.trigger('click')
    expect(wrapper.emitted('action')).toHaveLength(1)
  })

  it('error 语义使用 alert 且允许业务动作插槽', () => {
    const wrapper = mount(AppStatusNotice, {
      props: { tone: 'error', title: '同步失败' },
      slots: { action: '<button class="custom-action">查看详情</button>' },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.attributes('role')).toBe('alert')
    expect(wrapper.attributes('aria-live')).toBe('assertive')
    expect(wrapper.get('.custom-action').text()).toBe('查看详情')
  })

  it('同步中的持久提示暴露 busy 语义并使用统一动态反馈', () => {
    const wrapper = mount(AppStatusNotice, {
      props: { title: '正在同步偏好', loading: true },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.attributes('aria-busy')).toBe('true')
    expect(wrapper.classes()).toContain('is-loading')
  })

  it('图标、文案和动作按容器垂直居中，同行文案按基线对齐', () => {
    expect(appStatusNoticeSource).toContain('align-items: center')
    expect(appStatusNoticeSource).toContain('align-items: baseline')
    expect(appStatusNoticeSource).not.toContain('margin-top: 2px')
  })
})
