// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import AppHoverInfo from '../AppHoverInfo'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import CompareQueueRail from '@/components/CompareQueueRail.vue'

function mountRail(overrides: Record<string, unknown> = {}) {
  return mount(CompareQueueRail, {
    props: {
      items: [
        { key: 'A', label: '板块A', active: true },
        { key: 'B', label: '板块B' },
      ],
      ...overrides,
    },
    global: { plugins: [ElementPlus] },
  })
}

describe('CompareQueueRail', () => {
  it('渲染队列标签、chip 与上限提示', () => {
    const wrapper = mountRail({ hint: '勾选左侧板块加入，最多 6 个' })
    expect(wrapper.text()).toContain('对比队列')
    expect(wrapper.text()).toContain('板块A')
    expect(wrapper.text()).toContain('板块B')
    expect(wrapper.text()).toContain('勾选左侧板块加入，最多 6 个')
  })

  it('chip 以 role=button 承载激活并经 aria-pressed 暴露激活态', () => {
    const wrapper = mountRail()
    const chips = wrapper.findAll('.compare-queue-chip')
    expect(chips[0]!.classes()).toContain('active')
    expect(chips[1]!.classes()).not.toContain('active')
    expect(chips[0]!.attributes('role')).toBe('button')
    expect(chips[0]!.attributes('aria-pressed')).toBe('true')
  })

  it('不使用 el-button 或私有原生 button，名称为继承颜色的 span', () => {
    const wrapper = mountRail()
    expect(wrapper.find('.compare-queue-activate').exists()).toBe(false)
    expect(wrapper.find('.el-button').exists()).toBe(false)
    expect(wrapper.get('.compare-queue-name').element.tagName).toBe('SPAN')
  })

  it('点击 chip 发出 activate，点击移除发出 remove 且不连击 activate', async () => {
    const wrapper = mountRail()
    await wrapper.findAll('.compare-queue-chip')[1]!.trigger('click')
    expect(wrapper.emitted('activate')).toEqual([['B']])
    await wrapper.findAll('.compare-queue-remove')[0]!.trigger('click')
    expect(wrapper.emitted('remove')).toEqual([['A']])
    expect(wrapper.emitted('activate')).toEqual([['B']])
  })

  it('键盘 Enter 在 chip 上激活；焦点在移除钮时 .self 拦截不触发激活', async () => {
    const wrapper = mountRail()
    await wrapper.findAll('.compare-queue-chip')[0]!.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('activate')).toEqual([['A']])
    await wrapper.findAll('.compare-queue-remove')[0]!.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('activate')).toEqual([['A']])
  })

  it('仅剩激活项时隐藏移除按钮', () => {
    const wrapper = mountRail({ items: [{ key: 'A', label: '板块A', active: true }] })
    expect(wrapper.find('.compare-queue-remove').exists()).toBe(false)
  })

  it('错误项保留 error 类并通过共享提示提供原因', () => {
    const wrapper = mountRail({ items: [{ key: 'A', label: '板块A', active: true, error: '加载失败' }] })
    const chip = wrapper.get('.compare-queue-chip')
    expect(chip.classes()).toContain('error')
    expect(chip.attributes('title')).toBeUndefined()
    expect(wrapper.findComponent(AppHoverInfo).vm.$attrs.content).toBe('加载失败')
  })

  it('按 testIdPrefix 生成稳定 testid', () => {
    const wrapper = mountRail({ testIdPrefix: 'sectors' })
    expect(wrapper.find('[data-testid="sectors-compare-rail"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="sectors-compare-B"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="sectors-remove-B"]').exists()).toBe(true)
  })

  it('达到上限后隐藏上限提示', () => {
    const wrapper = mountRail({ max: 2, hint: '最多 2 个' })
    expect(wrapper.text()).not.toContain('最多 2 个')
  })
})
