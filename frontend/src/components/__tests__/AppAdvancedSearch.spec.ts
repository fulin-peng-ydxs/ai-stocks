// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, reactive } from 'vue'
import ElementPlus from 'element-plus'
import AppAdvancedSearch from '../AppAdvancedSearch.vue'
import { SEARCH_COMPONENT_VALUE, SEARCH_RUNTIME_META } from '@/layout/searchContext'
import { useLayoutConfig } from '@/layout/useLayoutConfig'
import { getPageLayout } from '@/layout/pageRegistry'
import { resolveCommonFields, searchSummary, type SearchFieldState } from '@/layout/searchGroups'

function setup(overrides: Record<string, SearchFieldState> = {}) {
  localStorage.clear()
  const config = useLayoutConfig(getPageLayout('user-manage'))
  const states = reactive<Record<string, SearchFieldState>>({
    tenant: { value: '', available: false },
    role: { value: 'reader', summary: '只读角色', clear: vi.fn() },
    status: { value: '' },
    keyword: { value: '' },
    ...overrides,
  })
  const mounted = vi.fn()
  const Field = defineComponent({ mounted, setup: () => () => h('input', { 'data-input': '', value: '未提交草稿' }) })
  const wrapper = mount(AppAdvancedSearch, {
    attachTo: document.body,
    props: { group: 'users', states },
    slots: { role: () => h(Field), status: '<input aria-label="状态" />', keyword: '<input aria-label="关键词" />' },
    global: { plugins: [ElementPlus], provide: { [SEARCH_COMPONENT_VALUE as symbol]: config.componentValueOf, [SEARCH_RUNTIME_META as symbol]: reactive({}) } },
  })
  return { wrapper, config, states, mounted }
}

describe('列表高级搜索', () => {
  it('默认不重复标题，无可见提示的控件显式提供左侧标签', async () => {
    const { wrapper, states } = setup()
    await wrapper.get('[data-search-toggle]').trigger('click')
    expect(wrapper.findAll('.app-advanced-search__label')).toHaveLength(0)
    states.role.selfLabelled = false
    await nextTick()
    expect(wrapper.get('[data-search-field="role"] .app-advanced-search__label').text()).toBe('角色')
    expect(wrapper.get('[data-search-field="role"]').attributes('aria-label')).toBe('角色')
    wrapper.unmount()
  })

  it('达到三项后默认收起，隐藏的生效条件显示摘要，收展不重建控件或清空值', async () => {
    const { wrapper, states, mounted } = setup()
    expect(wrapper.get('[data-search-field="role"]').isVisible()).toBe(false)
    expect(wrapper.get('[data-search-toggle]').text()).toContain('（1）')
    expect(wrapper.text()).toContain('只读角色')
    await wrapper.get('[data-search-toggle]').trigger('click')
    expect(wrapper.get('[data-search-field="role"]').isVisible()).toBe(true)
    await wrapper.get('[data-search-toggle]').trigger('click')
    expect(states.role.value).toBe('reader')
    expect(mounted).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('更换常显成员保留控件实例与输入草稿，收起态立即按新成员重新分配', async () => {
    const { wrapper, config, mounted } = setup()
    const input = wrapper.get('[data-input]').element
    config.setComponentKnob('head', 'commonFields', ['role', 'keyword'])
    await nextTick()
    expect(wrapper.get('[data-search-field="role"]').isVisible()).toBe(true)
    expect(wrapper.get('[data-search-field="status"]').isVisible()).toBe(false)
    expect(wrapper.get('[data-input]').element).toBe(input)
    expect(mounted).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('权限/模式变化不足三项时全显，不通过加载状态移除字段', async () => {
    const { wrapper, states } = setup()
    states.role.available = false
    await nextTick()
    expect(wrapper.find('[data-search-toggle]').exists()).toBe(false)
    expect(wrapper.get('[data-search-field="keyword"]').isVisible()).toBe(true)
    expect(wrapper.get('[data-search-field="status"]').isVisible()).toBe(true)
    wrapper.unmount()
  })

  it('摘要可定位并聚焦，清除只执行对应字段的领域回调', async () => {
    const { wrapper, states } = setup()
    await wrapper.get('.app-advanced-search__summary .el-button').trigger('click')
    expect(document.activeElement).toBe(wrapper.get('[data-input]').element)
    await wrapper.get('[data-search-toggle]').trigger('click')
    await wrapper.get('.el-tag__close').trigger('click')
    expect(states.role.clear).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('高级字段输入错误时禁止收起，定位字段并保留草稿', async () => {
    const { wrapper } = setup({ role: { value: 'reader', error: '请修正条件' } })
    await wrapper.get('[data-search-toggle]').trigger('click')
    await wrapper.get('[data-search-toggle]').trigger('click')
    expect(wrapper.get('[data-search-toggle]').attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('[role="alert"]').text()).toBe('请修正条件')
    wrapper.unmount()
  })

  it('旧字段、重复值、权限变化回退到有效默认，空和布尔条件摘要按实际限制判断', () => {
    const candidates = [{ key: 'status' }, { key: 'keyword' }, { key: 'role' }]
    expect(resolveCommonFields(['deleted', 'role', 'role'], candidates, ['status', 'keyword'])).toEqual(['role', 'status'])
    expect(searchSummary({ value: true })).toBe('是')
    expect(searchSummary({ value: false })).toBe('')
    expect(searchSummary({ value: '  ' })).toBe('')
    expect(searchSummary({ value: null, summary: '过期的股票名称' })).toBe('')
    expect(searchSummary({ value: false, active: true, summary: '不包含旧表' })).toBe('不包含旧表')
    expect(searchSummary({ value: ['2026-01-01', null], range: true })).toBe('2026-01-01 至 不限')
    expect(searchSummary({ value: ['a', 'b'] })).toBe('a、b')
    expect(searchSummary({ value: ['a', 'b'], active: false })).toBe('')
    expect(searchSummary({ value: ['a'], options: [{ value: 'a', label: '已启用' }] })).toBe('已启用')
  })
})
