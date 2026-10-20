// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppFormHelp from '@/components/AppFormHelp.vue'

describe('AppFormHelp', () => {
  it.each(['单行说明', '较长的说明依然只有一个标记，正文按可用宽度自然换行。'.repeat(4)])('标记与正文独立承载，不根据文本行数切换规则', (text) => {
    const wrapper = mount(AppFormHelp, { slots: { default: text } })
    expect(wrapper.attributes('role')).toBe('note')
    expect(wrapper.findAll('.app-form-help__marker')).toHaveLength(1)
    expect(wrapper.get('.app-form-help__marker').attributes('aria-hidden')).toBe('true')
    expect(wrapper.get('.app-form-help__content').text()).toBe(text)
    expect(wrapper.classes()).toContain('app-caption-text')
  })

  it('保留说明中的操作入口，警示说明仍使用同一结构', async () => {
    const wrapper = mount(AppFormHelp, {
      props: { tone: 'warning' },
      slots: { default: '请先<button>检查设置</button>再保存' },
    })
    expect(wrapper.classes()).toContain('app-form-help--warning')
    expect(wrapper.get('.app-form-help__content button').text()).toBe('检查设置')
    await wrapper.setProps({ tone: 'default' })
    expect(wrapper.classes()).not.toContain('app-form-help--warning')
    expect(wrapper.findAll('.app-form-help__marker')).toHaveLength(1)
  })
})
