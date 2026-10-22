// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import StockRuleChecklistEditor from '../StockRuleChecklistEditor.vue'
import StockRuleConditionChecklist from '../StockRuleConditionChecklist.vue'
import type { DraftStockRule, StockChecklistItem } from '@/api/tradeDiscipline'
import { defineComponent, h } from 'vue'
import { provideTradeDisciplineCategories, tradeConditionMeta } from '@/composables/useTradeDisciplineCategories'
import { normalizeChecklist } from '@/utils/tradeDisciplineConditions'

const items: StockChecklistItem[] = [
  { item_id: 'a', category: 'technical', text: '多头排列涨幅不超过50%', display_order: 1 },
  { item_id: 'b', category: 'technical', text: '一年内涨幅不超过100%', display_order: 2 },
]
const rule: DraftStockRule = { detail_id: 's', name: '主升启动', max_capital: '20000', enabled: true,
  display_order: 1, content: '原文第一行\n\n补充说明', checklist_items: items }

describe('选股分类检查项', () => {
  it('新增字典分类进入编辑和折叠属性，删除分类后历史条件及违规仍然可见', async () => {
    const custom = [{ item_id: 'earnings', category: 'fundamental', category_label: '基本面旧名', text: '业绩增长', display_order: 1 }]
    expect(normalizeChecklist(custom)).toEqual(custom)
    const host = defineComponent({
      setup() {
        const dictionary = provideTradeDisciplineCategories()
        dictionary.categories.value = [{ value: 'technical', label: '技术形态' }, { value: 'fundamental', label: '基本面新名' }]
        expect(tradeConditionMeta(dictionary.categories.value).stockConditions.collapseSections).toContainEqual({ key: 'fundamental', label: '基本面新名' })
        return () => h(StockRuleChecklistEditor, { modelValue: custom })
      },
    })
    const editor = mount(host, { global: { plugins: [ElementPlus] } })
    const category = editor.get('[data-condition-section="fundamental"] .config-panel-section__head')
    expect(category.text()).toContain('基本面新名')
    expect(category.attributes('aria-expanded')).toBe('false')
    await category.trigger('click')
    expect((editor.get('[data-checklist-id="earnings"] textarea').element as HTMLTextAreaElement).value).toBe('业绩增长')
    const history = mount(StockRuleConditionChecklist, { props: { rule: { ...rule, checklist_items: custom }, checking: true, disabled: true, results: [{ item_id: 'earnings', status: 'no' }] }, global: { plugins: [ElementPlus] } })
    expect(history.get('[data-condition-section="fundamental"]').text()).toContain('基本面旧名')
    expect(history.get('[data-condition-section="fundamental"]').text()).toContain('不符合 1')
    expect(custom[0].category_label).toBe('基本面旧名')
    await flushPromises()
    editor.unmount()
    history.unmount()
  })

  it('动态分类读取并重置默认折叠，临时开合与核对结果独立保留', async () => {
    const custom = [{ item_id: 'c', category: 'custom', text: '自定义条件', display_order: 1 }]
    const results = [{ item_id: 'c', status: 'unknown' as const }]
    const wrapper = mount(StockRuleConditionChecklist, { props: { rule: { ...rule, checklist_items: custom }, checking: true, results,
      panelDefaults: { defaultCollapsed: [], sectionKeys: ['custom'], resetKey: 0 } }, global: { plugins: [ElementPlus] } })
    const head = () => wrapper.get('[data-condition-section="custom"] .config-panel-section__head')
    expect(head().attributes('aria-expanded')).toBe('true')
    await head().trigger('click')
    await wrapper.setProps({ panelDefaults: { defaultCollapsed: [], sectionKeys: ['custom'], resetKey: 0 } })
    expect(head().attributes('aria-expanded')).toBe('false')
    await wrapper.setProps({ panelDefaults: { defaultCollapsed: [], sectionKeys: ['custom'], resetKey: 1 } })
    expect(head().attributes('aria-expanded')).toBe('true')
    expect(wrapper.props('results')).toEqual(results)
    wrapper.unmount()
  })
  it('三个分类默认收起，独立开合且收起保留输入与核对，支持键盘展开', async () => {
    const wrapper = mount(StockRuleConditionChecklist, { attachTo: document.body, props: { rule, checking: true,
      results: [{ item_id: 'a', status: 'no' }, { item_id: 'b', status: 'unknown' }] }, global: { plugins: [ElementPlus] } })
    const group = (key: string) => wrapper.get(`[data-condition-section="${key}"]`)
    expect(wrapper.findAll('.config-panel-section__head').every(head => head.attributes('aria-expanded') === 'false')).toBe(true)
    expect(group('technical').get('.config-panel-section__head').text()).toContain('不符合 1 · 未知 1')
    const content = group('technical').get('.config-panel-section__body')
    const mounted = content.element
    expect(content.isVisible()).toBe(false)
    await group('technical').get('[role="button"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(content.isVisible()).toBe(true)
    await group('basic').get('[role="button"]').trigger('click')
    expect(content.isVisible()).toBe(true)
    await group('technical').get('[role="button"]').trigger('click')
    expect(content.isVisible()).toBe(false)
    expect(content.element).toBe(mounted)
    expect(wrapper.props('results')).toEqual([{ item_id: 'a', status: 'no' }, { item_id: 'b', status: 'unknown' }])
    wrapper.unmount()
  })

  it('编辑、核对和历史读取相同默认，迟到配置保留临时开合，显式重置不丢输入结果', async () => {
    const defaults = { defaultCollapsed: ['risk', 'technical'], resetKey: 0 }
    const results = [{ item_id: 'a', status: 'no' as const }]
    const editor = mount(StockRuleChecklistEditor, {
      props: { modelValue: items, rule, panelDefaults: defaults },
      slots: { notes: '<textarea>未保存说明</textarea>' }, global: { plugins: [ElementPlus] },
    })
    const checkin = mount(StockRuleConditionChecklist, {
      props: { rule, results, checking: true, panelDefaults: defaults }, global: { plugins: [ElementPlus] },
    })
    const history = mount(StockRuleConditionChecklist, {
      props: { rule, results, checking: true, disabled: true, panelDefaults: defaults }, global: { plugins: [ElementPlus] },
    })
    const head = (wrapper: any, section: string) => wrapper.get(`[data-condition-section="${section}"] .config-panel-section__head`)
    for (const wrapper of [editor, checkin, history]) {
      expect(head(wrapper, 'basic').attributes('aria-expanded')).toBe('true')
      expect(head(wrapper, 'risk').attributes('aria-expanded')).toBe('false')
      expect(head(wrapper, 'notes').attributes('aria-expanded')).toBe('true')
      await head(wrapper, 'technical').trigger('click')
      // 远端默认到达不会把用户已经打开的技术形态收起。
      await wrapper.setProps({ panelDefaults: { defaultCollapsed: ['basic', 'risk', 'technical', 'notes'], resetKey: 0 } })
      expect(head(wrapper, 'technical').attributes('aria-expanded')).toBe('true')
      expect(head(wrapper, 'basic').attributes('aria-expanded')).toBe('false')
      await wrapper.setProps({ panelDefaults: { defaultCollapsed: ['basic', 'risk', 'technical', 'notes'], resetKey: 1 } })
      expect(head(wrapper, 'technical').attributes('aria-expanded')).toBe('false')
    }
    expect(editor.props('modelValue')).toEqual(items)
    expect((editor.get('[data-condition-section="notes"] textarea').element as HTMLTextAreaElement).value).toBe('未保存说明')
    expect(editor.emitted('update:modelValue')).toBeUndefined()
    expect(checkin.props('results')).toEqual(results)
    expect(checkin.emitted('update:results')).toBeUndefined()
    expect(history.get('[data-condition-section="technical"]').text()).toContain('不符合 1')
    for (const wrapper of [editor, checkin, history]) wrapper.unmount()
  })

  it('旧其他条件显示在技术形态，打开与折叠不改写历史对象', async () => {
    const legacy: DraftStockRule = { ...rule, checklist_items: [{ ...items[0], category: 'other' }] }
    const wrapper = mount(StockRuleConditionChecklist, { props: { rule: legacy }, global: { plugins: [ElementPlus] } })
    expect(wrapper.text()).not.toContain('其他条件')
    await wrapper.get('[data-condition-section="technical"] [role="button"]').trigger('click')
    expect(wrapper.get('[data-checklist-id="a"]').isVisible()).toBe(true)
    expect(legacy.checklist_items![0].category).toBe('other')
    expect(wrapper.emitted('update:results')).toBeUndefined()
  })
  it('宽度变化重新测高但不重置条件，卸载释放观察器', async () => {
    const observers: any[] = []
    vi.stubGlobal('ResizeObserver', class {
      callback: ResizeObserverCallback
      observe = vi.fn()
      unobserve = vi.fn()
      disconnect = vi.fn()
      constructor(callback: ResizeObserverCallback) { this.callback = callback; observers.push(this) }
    })
    try {
      const wrapper = mount(StockRuleChecklistEditor, { props: { modelValue: items }, global: { plugins: [ElementPlus] } })
      const observer = observers.find(observer => observer.observe.mock.calls.some(([element]: any[]) => element === wrapper.element))
      expect(observer).toBeDefined()
      observer.callback([{ contentRect: { width: 400 } }], observer)
      await flushPromises()
      expect(wrapper.get('textarea').element.value).toBe(items[0].text)
      expect(wrapper.props('modelValue')).toEqual(items)
      expect(wrapper.emitted('update:modelValue')).toBeUndefined()
      wrapper.unmount()
      expect(observer.disconnect).toHaveBeenCalled()
    } finally { vi.unstubAllGlobals() }
  })
  it('新增默认技术形态，修改分类、内容、组内排序及删除不丢失其它项', async () => {
    const wrapper = mount(StockRuleChecklistEditor, { props: { modelValue: items }, global: { plugins: [ElementPlus] } })
    const apply = async () => { await wrapper.setProps({ modelValue: wrapper.emitted('update:modelValue')!.at(-1)![0] as StockChecklistItem[] }); await flushPromises() }
    await wrapper.get('[data-testid="add-checklist-item"]').trigger('click')
    await apply()
    expect(wrapper.props('modelValue').at(-1)).toMatchObject({ category: 'technical', text: '' })
    const newId = wrapper.props('modelValue').at(-1)!.item_id
    await wrapper.get(`[data-checklist-id="${newId}"] textarea`).setValue('两个月处于30%区间')
    await apply()
    wrapper.findAllComponents({ name: 'ElSelect' }).at(-1)!.vm.$emit('update:modelValue', 'risk')
    await apply()
    expect(wrapper.get('section[aria-label="风险排除"] [role="button"]').attributes('aria-expanded')).toBe('true')
    expect(wrapper.text()).not.toContain('其他条件')
    const list = wrapper.findAllComponents({ name: 'AppReorderList' }).find(list => list.props('label') === '技术形态检查项排序')!
    list.vm.$emit('reorder', [...items].reverse())
    await apply()
    expect(wrapper.props('modelValue').map(item => item.item_id)).toEqual([newId, 'b', 'a'])
    await wrapper.get(`[data-checklist-id="a"] button[aria-label="删除检查项"]`).trigger('click')
    await apply()
    expect(wrapper.props('modelValue').map(item => item.item_id)).toEqual([newId, 'b'])
    expect(wrapper.props('modelValue')[0].text).toBe('两个月处于30%区间')
  })

  it('只读编辑不提供增删入口，核对默认未选，历史未知与未记录区分', async () => {
    const editor = mount(StockRuleChecklistEditor, { props: { modelValue: items, disabled: true }, global: { plugins: [ElementPlus] } })
    expect(editor.find('[data-testid="add-checklist-item"]').exists()).toBe(false)
    expect(editor.find('button[aria-label="删除检查项"]').exists()).toBe(false)
    const wrapper = mount(StockRuleConditionChecklist, { props: { rule, checking: true }, global: { plugins: [ElementPlus] } })
    expect(wrapper.findAllComponents({ name: 'ElSegmented' })[0].props('modelValue')).toBeUndefined()
    wrapper.findAllComponents({ name: 'ElSegmented' })[0].vm.$emit('update:modelValue', 'unknown')
    expect(wrapper.emitted('update:results')!.at(-1)![0]).toEqual([{ item_id: 'a', status: 'unknown' }])
    await wrapper.setProps({ results: [{ item_id: 'a', status: 'yes' }, { item_id: 'b', status: 'unknown' }] })
    wrapper.findAllComponents({ name: 'ElSegmented' })[0].vm.$emit('update:modelValue', 'yes')
    expect(wrapper.emitted('update:results')!.at(-1)![0]).toEqual(wrapper.props('results'))
    await wrapper.setProps({ results: [{ item_id: 'a', status: 'unknown' }], disabled: true })
    expect(wrapper.findAllComponents({ name: 'ElSegmented' })).toHaveLength(0)
    expect(wrapper.get('[data-checklist-id="a"]').text()).toContain('未知')
    expect(wrapper.get('[data-checklist-id="b"]').text()).toContain('未记录')
    expect(wrapper.get('[data-condition-section="notes"] p').text()).toBe(rule.content)
  })
})
