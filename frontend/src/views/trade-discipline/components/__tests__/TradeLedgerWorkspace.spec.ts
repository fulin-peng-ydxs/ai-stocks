// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElMessageBox } from 'element-plus'
import TradeLedgerWorkspace from '../TradeLedgerWorkspace.vue'
import TradeOperationEditor from '../TradeOperationEditor.vue'
import FixedDecimalInput from '../FixedDecimalInput.vue'
import AppControlRow from '@/components/AppControlRow.vue'
import { ledgerEventPayload, type LedgerContext } from '@/api/tradeLedger'
import { useAuthStore } from '@/stores/auth'
import { useStockSet } from '@/stores/stockSet'

const api = vi.hoisted(() => ({ context: vi.fn(), initialize: vi.fn(), submit: vi.fn(), preview: vi.fn(), history: vi.fn(), revision: vi.fn(), withdraw: vi.fn() }))
vi.mock('@/api/tradeLedger', async (original) => ({
  ...await original<typeof import('@/api/tradeLedger')>(),
  getLedgerContext: api.context, initializeLedger: api.initialize,
  submitLedger: api.submit, previewLedger: api.preview, getLedgerHistory: api.history, getLedgerRevision: api.revision, withdrawLedger: api.withdraw,
}))
const version = { rule_id: 'r', version_no: 1, name: '趋势纪律', capital: '100000',
  stock_rules: [{ detail_id: 's', name: '趋势选股', enabled: true, display_order: 1, max_capital: null, content: null }],
  action_rules: [{ detail_id: 'a', name: '回踩买入', action_type: 'buy' as const, action_subtype: 'open_position', enabled: true, display_order: 1, content: null }] }
function context(extra: Partial<LedgerContext> = {}): LedgerContext {
  return { trade_date: '2026-10-23', account_revision: 1, initialized_on: '2026-10-23',
    can_edit: true, latest_trade_date: null, current_revision_no: 0, snapshot: null,
    rules: [version], opening_positions: [], opening_cash: null, positions: [], cash: null, ...extra }
}
function mountWorkspace(props = {}, editorStub = true, navigation = { role: 'normal', permissions: [] as string[] }) {
  const pinia = createPinia()
  const auth = useAuthStore(pinia)
  auth.role = navigation.role
  auth.permissions = navigation.permissions
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/trade-discipline', component: { template: '<div />' } },
    { path: '/stocks/:code', name: 'stock-detail', component: { template: '<div />' } },
  ] })
  return mount(TradeLedgerWorkspace, { props: { mode: 'checkin', tradeDate: '2026-10-23', canSubmit: true, ...props },
    global: { plugins: [pinia, ElementPlus, router], directives: { permission: {} },
      stubs: { StockOptionSelect: true, TradeOperationEditor: editorStub, AppDatePicker: true, TradeDatePicker: true } } })
}
beforeEach(() => {
  vi.clearAllMocks()
  api.context.mockResolvedValue(context())
  api.history.mockResolvedValue({ total: 0, list: [] })
  api.preview.mockResolvedValue({ assessment: 'complied', events: [], positions: [], evaluations: [], peak_positions: 0 })
  api.submit.mockResolvedValue({})
})
describe('账户日结简化填报', () => {
  it.each(['代码', '股票名称'])('持仓%s跳转个股详情，集合去重且保留持仓日期的返回入口', async column => {
    const position = { stock_code: '600873.SH', stock_name: '梅花生物', quantity: '400',
      available_quantity: '400', cost: '4000', market_value: '4000', unrealized_pnl: '0',
      quote_date: '2026-10-23', rule_id: 'r', stock_rule_id: 's' }
    api.context.mockResolvedValue(context({ positions: [position,
      { ...position, stock_rule_id: 'another-group' },
      { ...position, stock_code: '600356.SH', stock_name: '恒丰纸业' },
    ] }))
    const wrapper = mountWorkspace({ mode: 'positions' }, true, { role: 'normal', permissions: ['stocks:view'] })
    try {
      await flushPromises()
      const links = wrapper.findAll('a[href="/stocks/600356.SH"]')
      expect(links.map(link => link.text())).toEqual(['600356.SH', '恒丰纸业'])
      await links[column === '代码' ? 0 : 1]!.trigger('click')
      await flushPromises()
      expect(wrapper.vm.$router.currentRoute.value.path).toBe('/stocks/600356.SH')
      const collection = useStockSet(wrapper.vm.$pinia)
      expect(collection.items).toEqual([
        { code: '600873.SH', name: '梅花生物' }, { code: '600356.SH', name: '恒丰纸业' },
      ])
      expect(collection.returnPath).toBe('/trade-discipline?tab=positions&trade_date=2026-10-23')
      expect(collection.label).toBe('交易纪律持仓')
      expect(api.submit).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it('没有个股查看权限时保持普通文字，授权变化即时更新链接', async () => {
    api.context.mockResolvedValue(context({ positions: [{ stock_code: '600873.SH', stock_name: '梅花生物',
      quantity: '400', available_quantity: '400', cost: null, market_value: null, unrealized_pnl: null,
      quote_date: null, rule_id: 'r', stock_rule_id: 's' }] }))
    const wrapper = mountWorkspace({ mode: 'positions' })
    try {
      await flushPromises()
      expect(wrapper.findAll('a[href^="/stocks/"]')).toHaveLength(0)
      expect(wrapper.text()).toContain('600873.SH')
      expect(wrapper.text()).toContain('梅花生物')
      const auth = useAuthStore(wrapper.vm.$pinia)
      auth.permissions = ['stocks:view']
      await flushPromises()
      expect(wrapper.findAll('a[href="/stocks/600873.SH"]')).toHaveLength(2)
      auth.permissions = []
      auth.role = 'system'
      await flushPromises()
      expect(wrapper.findAll('a[href="/stocks/600873.SH"]')).toHaveLength(2)
      auth.role = 'normal'
      await flushPromises()
      expect(wrapper.findAll('a[href^="/stocks/"]')).toHaveLength(0)
    } finally { wrapper.unmount() }
  })

  it('移除手动核对按钮后，完整成交仍自动预览且可直接提交', async () => {
    vi.useFakeTimers()
    const wrapper = mountWorkspace()
    try {
      await flushPromises()
      expect(wrapper.get('.app-workspace-pane__footer').findAll('button')).toHaveLength(1)
      expect(wrapper.text()).not.toContain('核对持仓与规则')
      wrapper.findComponent(TradeOperationEditor).vm.$emit('update:modelValue', [{
        event_id: 'auto-preview', stock_code: '600000.SH', stock_name_snapshot: '浦发银行', side: 'buy',
        stock_rule_id: 's', action_rule_id: 'a', price: '10', quantity: '100', amount: '1000',
        fee: '5', operated_at: '2026-10-23T10:00:00', note: null, display_order: 1,
      }])
      await flushPromises()
      await vi.advanceTimersByTimeAsync(700)
      await flushPromises()
      expect(api.preview).toHaveBeenCalledTimes(1)
      expect(api.preview.mock.calls[0][0].events[0]).toMatchObject({ price: '10', quantity: '100', fee: '5' })
      expect(api.submit).not.toHaveBeenCalled()
      await wrapper.get('.app-workspace-pane__footer button').trigger('click')
      await flushPromises()
      expect(api.submit).toHaveBeenCalledTimes(1)
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })
  it('浮动盈亏按正负展示金融颜色，零值和缺失值不套用盈亏色', async () => {
    api.context.mockResolvedValue(context({ positions: [
      ...['45.00', '-45.00', '0.00', null].map((pnl, index) => ({ stock_code: `60000${index}.SH`,
        stock_name: `股票${index}`, quantity: '100', available_quantity: '100', cost: '1000',
        market_value: '1000', unrealized_pnl: pnl, quote_date: '2026-10-23', rule_id: 'r', stock_rule_id: 's' })),
    ] }))
    const wrapper = mountWorkspace({ mode: 'positions' })
    try {
      await flushPromises()
      expect(wrapper.get('.up').text()).toBe('+45.00')
      expect(wrapper.get('.down').text()).toBe('-45.00')
      expect(wrapper.get('.muted').text()).toBe('数据不完整')
      expect(wrapper.findAll('.up, .down')).toHaveLength(2)
      expect(wrapper.findAll('th.is-right').map(node => node.text())).toEqual([
        '数量', '可卖数量', '总成本（元）', '市值（元）', '浮动盈亏（元）',
      ])
    } finally { wrapper.unmount() }
  })
  it.each(['cancel', 'success', 'failure', 'stale'] as const)('撤回确认使用统一弹窗，%s 分支不遗留抽屉或丢失失败反馈', async outcome => {
    const snapshot: NonNullable<LedgerContext['snapshot']> = { trade_date: '2026-10-23', events: [], positions: [],
      opening_positions: [], omissions: [], rules: [version], assessment: 'complied', complete: true,
      peak_positions: 0, buy_amount: '0', sell_amount: '0', fee: '0', net_outflow: '0',
      cash: null, realized_pnl: null, review_note: null, evaluations: [] }
    api.context.mockResolvedValue(context({ snapshot, latest_trade_date: '2026-10-23', current_revision_no: 1 }))
    const confirm = vi.spyOn(ElMessageBox, 'confirm')
    let finishConfirmation: (() => void) | undefined
    if (outcome === 'cancel') confirm.mockRejectedValue('cancel')
    else if (outcome === 'stale') confirm.mockImplementation(() => new Promise(resolve => { finishConfirmation = () => resolve('confirm' as never) }))
    else confirm.mockResolvedValue('confirm' as never)
    if (outcome === 'failure') api.withdraw.mockRejectedValue(new Error('账户已变化，请刷新后重试'))
    else api.withdraw.mockResolvedValue({})
    const wrapper = mountWorkspace()
    try {
      await flushPromises()
      await wrapper.findAll('button').find(node => node.text() === '撤回最新日结')!.trigger('click')
      await flushPromises()
      if (outcome === 'stale') {
        await wrapper.setProps({ tradeDate: '2026-10-26' })
        await flushPromises()
        finishConfirmation!()
        await flushPromises()
      }
      expect(confirm).toHaveBeenCalledWith(expect.stringContaining('2026-10-23'), '撤回最新日结', expect.objectContaining({
        confirmButtonText: '确认撤回', cancelButtonText: '取消', confirmButtonType: 'danger', closeOnClickModal: false,
      }))
      expect(wrapper.findAllComponents({ name: 'AppDetailDrawer' }).some(drawer => drawer.attributes('title') === '撤回最新日结')).toBe(false)
      if (outcome === 'cancel' || outcome === 'stale') expect(api.withdraw).not.toHaveBeenCalled()
      else { expect(api.withdraw).toHaveBeenCalledTimes(1); expect(api.withdraw).toHaveBeenCalledWith('2026-10-23', 1) }
      if (outcome === 'success') expect(wrapper.emitted('submitted')).toHaveLength(1)
      if (outcome === 'failure') {
        expect(wrapper.text()).toContain('账户已变化，请刷新后重试')
        expect(wrapper.emitted('submitted')).toBeUndefined()
        expect(wrapper.findAll('button').find(node => node.text() === '撤回最新日结')!.attributes('disabled')).toBeUndefined()
      }
    } finally {
      confirm.mockRestore()
      wrapper.unmount()
    }
  })
  it('空白草稿不作为已录成交，唯一候选默认选中，关联只追加核对不重复记账', async () => {
    const second = { ...version, rule_id: 'second', name: '第二套规则' }
    api.context.mockResolvedValue(context({ rules: [version, second] }))
    const wrapper = mountWorkspace()
    await flushPromises()
    const firstEditor = wrapper.findComponent(TradeOperationEditor)
    const draft = { event_id: 'one-fill', stock_code: '', stock_name_snapshot: '', side: 'buy',
      stock_rule_id: 's', action_rule_id: 'a', price: '10', quantity: '100', amount: '1000',
      fee: '0', operated_at: '2026-10-23T10:00:00', note: null, display_order: 1 }
    firstEditor.vm.$emit('update:modelValue', [draft])
    const target = wrapper.get('.ledger-entry-context').findComponent({ name: 'AppSelect' })
    target.vm.$emit('update:modelValue', 'second')
    target.vm.$emit('change', 'second')
    await flushPromises()
    expect(wrapper.find('[data-testid="ledger-link-trade-row"]').exists()).toBe(false)
    firstEditor.vm.$emit('update:modelValue', [{ ...draft, stock_code: '600000.SH', stock_name_snapshot: '浦发银行' }])
    await flushPromises()
    const row = wrapper.get('[data-testid="ledger-link-trade-row"]')
    expect(row.findComponent({ name: 'ElSelect' }).props('modelValue')).toBe('one-fill')
    expect(row.text()).toContain('浦发银行 · 买入 · 10:00:00')
    await row.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="ledger-link-trade-row"]').exists()).toBe(false)
    const secondEditor = wrapper.findAllComponents(TradeOperationEditor).find(editor => editor.props('version').rule_id === 'second')!
    expect(secondEditor.props('modelValue')).toEqual([expect.objectContaining({ event_id: 'one-fill', linked: true })])
    await wrapper.findAll('button').find(node => node.text() === '提交当日记录')!.trigger('click')
    await flushPromises()
    const events = api.submit.mock.calls[0][0].events
    expect(events).toHaveLength(1)
    expect(events[0]).toMatchObject({ event_id: 'one-fill', rule_id: 'r', rule_checks: [expect.objectContaining({ rule_id: 'second' })] })
    wrapper.unmount()
  })
  it('多个成交不擅自选择，移除选中成交后清理失效引用', async () => {
    api.context.mockResolvedValue(context({ rules: [version, { ...version, rule_id: 'second', name: '第二套规则' }] }))
    const wrapper = mountWorkspace({ preferredRuleId: 'second' })
    await flushPromises()
    const target = wrapper.get('.ledger-entry-context').findComponent({ name: 'AppSelect' })
    target.vm.$emit('update:modelValue', 'r')
    target.vm.$emit('change', 'r')
    const editor = wrapper.findComponent(TradeOperationEditor)
    const draft = { event_id: 'one', stock_code: '600000.SH', stock_name_snapshot: '浦发银行', side: 'buy',
      stock_rule_id: 's', action_rule_id: 'a', price: '10', quantity: '100', amount: '1000',
      fee: '0', operated_at: '2026-10-23T10:00:00', note: null, display_order: 1 }
    const other = { ...draft, event_id: 'two', display_order: 2 }
    editor.vm.$emit('update:modelValue', [draft, other])
    await flushPromises()
    const source = () => wrapper.get('[data-testid="ledger-link-trade-row"]').findComponent({ name: 'AppSelect' })
    expect(source().findComponent({ name: 'ElSelect' }).props('modelValue')).toBe('')
    source().vm.$emit('update:modelValue', 'one')
    await flushPromises()
    editor.vm.$emit('update:modelValue', [other])
    await flushPromises()
    expect(source().findComponent({ name: 'ElSelect' }).props('modelValue')).toBe('two')
    editor.vm.$emit('update:modelValue', [])
    await flushPromises()
    expect(wrapper.find('[data-testid="ledger-link-trade-row"]').exists()).toBe(false)
    wrapper.unmount()
  })
  it('持仓摘要与日期共用顶部工具行，规则仍在下方填写区切换', async () => {
    api.context.mockResolvedValue(context({ rules: [version, { ...version, rule_id: 'second', name: '第二套规则' }] }))
    const wrapper = mountWorkspace()
    await flushPromises()
    const toolbar = wrapper.get('.app-workspace-pane__toolbar')
    expect(toolbar.findComponent({ name: 'TradeDatePicker' }).exists()).toBe(true)
    expect(toolbar.get('.ledger-summary').text()).toContain('期初持仓 0 只')
    expect(toolbar.findComponent({ name: 'AppSelect' }).exists()).toBe(false)
    const selector = wrapper.get('.ledger-entry-context').findComponent({ name: 'AppSelect' })
    expect(selector.exists()).toBe(true)
    expect(selector.findComponent({ name: 'ElSelect' }).props('emptyValues')).toEqual([null, undefined])
    selector.vm.$emit('update:modelValue', 'second')
    await flushPromises()
    selector.vm.$emit('change', 'second')
    await flushPromises()
    expect(wrapper.findAllComponents(TradeOperationEditor).map(editor => editor.props('version').rule_id)).toContain('second')
    expect(wrapper.find('.ledger-primary .ledger-entry-context').exists()).toBe(false)
    wrapper.unmount()
  })
  it.each([
    ['未初始化', {}, { initialized_on: null }],
    ['持仓页', { mode: 'positions' }, {}],
    ['历史只读', {}, { can_edit: false }],
    ['无填报权限', { canSubmit: false }, {}],
  ])('%s不显示填写区操作规则入口', async (_name, props, extra) => {
    api.context.mockResolvedValue(context(extra))
    const wrapper = mountWorkspace(props)
    await flushPromises()
    expect(wrapper.find('.ledger-entry-context [aria-label="操作适用规则"]').exists()).toBe(false)
    expect(wrapper.find('.app-workspace-pane__footer').exists()).toBe(false)
    wrapper.unmount()
  })
  it('没有遗漏和调整时不渲染空框，新增后展开字段，删除后收起', async () => {
    const wrapper = mountWorkspace()
    await flushPromises()
    const panels = () => wrapper.findAllComponents({ name: 'TradeDisciplineSectionPanel' })
      .filter(panel => ['漏买漏卖', '持仓与资金调整'].includes(panel.props('title')))
    expect(panels()).toHaveLength(2)
    expect(panels().every(panel => !panel.find('[data-testid="trade-discipline-section-body"]').exists())).toBe(true)
    await wrapper.findAll('button').find(node => node.text() === '添加遗漏事项')!.trigger('click')
    expect(wrapper.find('[data-testid="ledger-omission-row"]').exists()).toBe(true)
    await wrapper.get('[data-testid="ledger-omission-row"] button').trigger('click')
    expect(panels().every(panel => !panel.find('[data-testid="trade-discipline-section-body"]').exists())).toBe(true)
    wrapper.unmount()
  })
  it('遗漏和调整行共用表单尺寸，删除只移除对应记录', async () => {
    const wrapper = mountWorkspace()
    await flushPromises()
    for (const label of ['添加遗漏事项', '记录持仓调整', '记录资金变动']) {
      await wrapper.findAll('button').find(node => node.text() === label)!.trigger('click')
    }
    const rows = wrapper.findAllComponents(AppControlRow).filter(row => row.attributes('data-testid')?.startsWith('ledger-'))
    expect(rows).toHaveLength(3)
    for (const row of rows) {
      expect(row.attributes('data-control-row')).toBe('large')
      expect(row.props('align')).toBe('start')
    }
    expect(wrapper.find('[aria-label="删除调整 1"]').exists()).toBe(true)
    await rows[0]!.find('button').trigger('click')
    expect(wrapper.find('[data-testid="ledger-omission-row"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-testid="ledger-adjustment-row"]')).toHaveLength(2)
    await wrapper.get('[aria-label="删除调整 1"]').trigger('click')
    expect(wrapper.findAll('[data-testid="ledger-adjustment-row"]')).toHaveLength(1)
    wrapper.unmount()
  })
  it('修正持仓调整数量时丢弃旧派生成本，送股切换也清除旧成本和减少方向', async () => {
    expect(ledgerEventPayload({ event_id: 'adjust', kind: 'position', rule_id: null,
      cost_price: '10', quantity: '200', amount: '1000' } as never).amount).toBeNull()
    const wrapper = mountWorkspace()
    await flushPromises()
    await wrapper.findAll('button').find(node => node.text() === '记录持仓调整')!.trigger('click')
    const formItem = (label: string) => wrapper.findAllComponents({ name: 'ElFormItem' }).find(node => node.props('label') === label)
    formItem('成本价（元/股，选填）')!.findComponent(FixedDecimalInput).vm.$emit('update:modelValue', '10')
    formItem('变动')!.findComponent({ name: 'AppSelect' }).vm.$emit('update:modelValue', 'sell')
    const category = formItem('调整类别')!.findComponent({ name: 'AppSelect' })
    category.vm.$emit('update:modelValue', 'bonus')
    category.vm.$emit('change', 'bonus')
    await flushPromises()
    expect(formItem('变动')).toBeUndefined()
    expect(formItem('成本价（元/股，选填）')).toBeUndefined()
    await wrapper.findAll('button').find(node => node.text() === '提交当日记录')!.trigger('click')
    await flushPromises()
    expect(api.submit.mock.calls[0][0].events[0]).toMatchObject({ side: 'buy', cost_price: null, amount: null })
    wrapper.unmount()
  })
  it('期初成本价随数量自动计算总成本，清空不当作零，提交原始单价', async () => {
    api.context.mockResolvedValue(context({ initialized_on: null, account_revision: 0 }))
    api.initialize.mockRejectedValue(new Error('保留草稿'))
    const wrapper = mountWorkspace()
    await flushPromises()
    await wrapper.findAll('button').find(node => node.text() === '添加期初股票')!.trigger('click')
    wrapper.findComponent({ name: 'StockOptionSelect' }).vm.$emit('update:modelValue', { code: '600000.SH', name: '浦发银行' })
    const inputs = wrapper.findAllComponents(FixedDecimalInput)
    inputs[0]!.vm.$emit('update:modelValue', '3')
    inputs[1]!.vm.$emit('update:modelValue', '10.1234')
    await flushPromises()
    expect(wrapper.text()).toContain('总成本：30.37 元')
    inputs[0]!.vm.$emit('update:modelValue', '6')
    await flushPromises()
    expect(wrapper.text()).toContain('总成本：60.74 元')
    inputs[1]!.vm.$emit('update:modelValue', null)
    await flushPromises()
    expect(wrapper.text()).toContain('总成本：未录入')
    inputs[1]!.vm.$emit('update:modelValue', '0')
    wrapper.findComponent({ name: 'ElCheckbox' }).vm.$emit('update:modelValue', true)
    await flushPromises()
    await wrapper.findAll('button').find(node => node.text() === '确认期初持仓')!.trigger('click')
    await flushPromises()
    expect(api.initialize.mock.calls[0][0].positions).toEqual([{ stock_code: '600000.SH', quantity: '6', cost_price: '0' }])
    wrapper.unmount()
  })
  it('资金类别决定方向，只有其他调整需要选择方向', async () => {
    const wrapper = mountWorkspace()
    await flushPromises()
    await wrapper.findAll('button').find(node => node.text() === '记录资金变动')!.trigger('click')
    const formItem = (label: string) => wrapper.findAllComponents({ name: 'ElFormItem' }).find(node => node.props('label') === label)
    expect(formItem('方向')).toBeUndefined()
    const category = formItem('变动类别')!.findComponent({ name: 'AppSelect' })
    category.vm.$emit('update:modelValue', 'withdrawal')
    category.vm.$emit('change', 'withdrawal')
    await flushPromises()
    expect(formItem('方向')).toBeUndefined()
    category.vm.$emit('update:modelValue', 'other')
    category.vm.$emit('change', 'other')
    await flushPromises()
    expect(formItem('方向')).toBeDefined()
    wrapper.unmount()
  })
  it('未补齐成交时展开错误卡片并保留填写，不发送保存请求', async () => {
    const wrapper = mountWorkspace({}, false)
    await flushPromises()
    const editor = wrapper.findComponent(TradeOperationEditor)
    await editor.get('[aria-label="添加买入操作"]').trigger('click')
    await flushPromises()
    await editor.get('[data-testid="operation-card-toggle"]').trigger('click')
    await wrapper.findAll('button').find(node => node.text() === '提交当日记录')!.trigger('click')
    await flushPromises()
    expect(api.submit).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('操作 1：信息未完整')
    expect(editor.get('[data-testid="operation-card-toggle"]').attributes('aria-expanded')).toBe('true')
    wrapper.unmount()
  })
  it('快捷入口指定第二套规则时，新增操作归入指定规则', async () => {
    const second = { ...version, rule_id: 'second', name: '第二套规则' }
    api.context.mockResolvedValue(context({ rules: [version, second] }))
    const wrapper = mountWorkspace({ preferredRuleId: 'second' })
    await flushPromises()
    expect(wrapper.findComponent(TradeOperationEditor).props('version').rule_id).toBe('second')
    wrapper.findComponent(TradeOperationEditor).vm.$emit('update:modelValue', [{
      client_key: 'fill-second', stock_code: '600000.SH', stock_name_snapshot: '浦发银行', side: 'buy',
      stock_rule_id: 's', action_rule_id: 'a', price: '10', quantity: '100', amount: '1000',
      fee: '0', operated_at: '2026-10-23T10:00:00', note: null, display_order: 1,
    }])
    await flushPromises()
    await wrapper.findAll('button').find(node => node.text() === '提交当日记录')!.trigger('click')
    await flushPromises()
    expect(api.submit.mock.calls[0][0].events[0].rule_id).toBe('second')
    wrapper.unmount()
  })
  it('显示已撤回属于高级条件，收起后保留摘要并可独立清除', async () => {
    const wrapper = mountWorkspace({ mode: 'history' })
    await flushPromises()
    const field = wrapper.get('[data-search-field="withdrawn"]')
    expect(field.attributes('style')).toContain('display: none')
    expect(wrapper.get('.app-advanced-search__commands').text()).not.toContain('显示已撤回')
    await wrapper.get('[data-search-toggle]').trigger('click')
    expect(field.attributes('style') || '').not.toContain('display: none')
    await field.findComponent({ name: 'ElCheckbox' }).setValue(true)
    await flushPromises()
    expect(api.history.mock.calls.at(-1)![2].include_withdrawn).toBe(true)
    await wrapper.get('[data-search-toggle]').trigger('click')
    expect(wrapper.get('.app-advanced-search__summary').text()).toContain('包含已撤回')
    await wrapper.get('.app-advanced-search__summary .el-tag__close').trigger('click')
    await flushPromises()
    expect(api.history.mock.calls.at(-1)![2].include_withdrawn).toBe(false)
    wrapper.unmount()
  })
  it('历史数字列与详情费用按数字对齐，变动类型作为可阅读的业务事实展示', async () => {
    const row = { trade_date: '2026-10-23', current_revision_no: 1, withdrawn: false,
      snapshot: { trade_date: '2026-10-23', rules: [], omissions: [], evaluations: [],
        events: [
          { kind: 'cash', direction: 'in', operated_at: '2026-10-23T09:00:00', amount: '10000', fee: '0' },
          { kind: 'trade', side: 'buy', operated_at: '2026-10-23T10:00:00', stock_name_snapshot: '浦发银行', quantity: '100', amount: '1000', fee: '5' },
          { kind: 'position', side: 'buy', operated_at: '2026-10-23T11:00:00', stock_name_snapshot: '浦发银行', quantity: '10', fee: '0' },
        ], assessment: 'complied', operation_count: 1, buy_amount: '1000', sell_amount: '0', fee: '5', peak_positions: 1 } }
    api.history.mockResolvedValue({ total: 1, list: [row] })
    api.revision.mockResolvedValue(row)
    const wrapper = mountWorkspace({ mode: 'history' })
    try {
      await flushPromises()
      expect(wrapper.findAll('th.is-right').map(node => node.text())).toEqual([
        '操作数', '买入额', '卖出额', '持仓峰值', '修订',
      ])
      expect(wrapper.find('.app-table-column--action').exists()).toBe(false)
      await wrapper.findAll('button').find(node => node.text() === '2026-10-23')!.trigger('click')
      await flushPromises()
      const tables = wrapper.findAllComponents({ name: 'AppDataTable' })
      const details = tables.find(table => table.props('embedded'))!
      expect(details.findAll('th.is-right').map(node => node.text())).toEqual(['数量', '金额', '费用'])
      const typeHeader = details.findAll('th').find(node => node.text() === '变动类型')!
      expect(typeHeader.classes()).toContain('is-center')
      expect(details.text()).toContain('资金流入')
      expect(details.text()).toContain('持仓调整·买入')
      expect(details.find('.app-table-column--action').exists()).toBe(false)
      expect(api.submit).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it('撤回历史可显式查看，详情说明不参与持仓统计且没有修正入口', async () => {
    const row = { trade_date: '2026-10-23', current_revision_no: 1, withdrawn: true,
      snapshot: { trade_date: '2026-10-23', events: [], rules: [], omissions: [], evaluations: [],
        assessment: 'complied', buy_amount: '0', sell_amount: '0', fee: '0', peak_positions: 0 } }
    api.history.mockImplementation((_page, _size, filters) => Promise.resolve({ total: filters.include_withdrawn ? 1 : 0,
      list: filters.include_withdrawn ? [row] : [] }))
    api.revision.mockResolvedValue(row)
    const wrapper = mountWorkspace({ mode: 'history' })
    await flushPromises()
    wrapper.findAllComponents({ name: 'ElCheckbox' }).find(node => node.text() === '显示已撤回')!.vm.$emit('update:modelValue', true)
    await flushPromises()
    expect(api.history.mock.calls.at(-1)![2].include_withdrawn).toBe(true)
    expect(wrapper.text()).toContain('已撤回')
    await wrapper.findAll('button').find(node => node.text() === '2026-10-23')!.trigger('click')
    await flushPromises()
    expect(api.revision).toHaveBeenCalledWith('2026-10-23', 1)
    expect(wrapper.text()).toContain('不参与持仓及统计')
    expect(wrapper.text()).not.toContain('前往修正最新记录')
    wrapper.unmount()
  })
  it('保存期间阻止离开，避免写入未结束时切换账户上下文', async () => {
    let finish!: (value: object) => void
    api.submit.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const wrapper = mountWorkspace()
    await flushPromises()
    await wrapper.findAll('button').find(node => node.text() === '提交当日记录')!.trigger('click')
    expect(wrapper.get('.ledger-entry-context').findComponent({ name: 'AppSelect' }).findComponent({ name: 'ElSelect' }).props('disabled')).toBe(true)
    expect(wrapper.get('.app-workspace-pane__footer').text()).not.toContain('核对持仓与规则')
    expect(wrapper.get('.app-workspace-pane__footer button').attributes('disabled')).toBeDefined()
    const exposed = wrapper.vm as unknown as { isDirty: () => boolean; requestLeave: () => Promise<boolean> }
    expect(exposed.isDirty()).toBe(true)
    expect(await exposed.requestLeave()).toBe(false)
    finish({})
    await flushPromises()
    wrapper.unmount()
  })
  it('起算日前不显示未来持仓和填报按钮', async () => {
    api.context.mockResolvedValue(context({ initialized_on: '2026-10-26', can_edit: false }))
    const wrapper = mountWorkspace()
    await flushPromises()
    expect(wrapper.text()).toContain('该日期早于账本起算日')
    expect(wrapper.findAll('button').some(node => node.text() === '提交当日记录')).toBe(false)
    wrapper.unmount()
  })
  it('无自评或持仓数输入，手填仅承载真实成交和遗漏', async () => {
    const wrapper = mountWorkspace()
    await flushPromises()
    expect(wrapper.text()).toContain('漏买漏卖')
    expect(wrapper.text()).not.toContain('履约自评')
    expect(wrapper.text()).not.toContain('未履约原因')
    expect(wrapper.findComponent(TradeOperationEditor).props('automatic')).toBe(true)
    expect(wrapper.findAll('input').some(input => input.attributes('aria-label') === '当日最大同时持仓数')).toBe(false)
    wrapper.unmount()
  })
  it('空仓初始化需显式确认，不能自动把未初始化解释为空仓', async () => {
    api.context.mockResolvedValue(context({ initialized_on: null, can_edit: false, account_revision: 0 }))
    const wrapper = mountWorkspace()
    await flushPromises()
    const button = wrapper.findAll('button').find(node => node.text() === '确认期初持仓')!
    expect(button.attributes('disabled')).toBeDefined()
    await button.trigger('click')
    expect(api.initialize).not.toHaveBeenCalled()
    wrapper.findComponent({ name: 'ElCheckbox' }).vm.$emit('update:modelValue', true)
    await flushPromises()
    await button.trigger('click')
    await flushPromises()
    expect(api.initialize).toHaveBeenCalledWith({ trade_date: '2026-10-23', expected_revision: 0, positions: [], cash: null })
    wrapper.unmount()
  })
  it('提交只发送成交事实、稳定标识和并发版本，不发送客户端履约结论', async () => {
    const wrapper = mountWorkspace()
    await flushPromises()
    wrapper.findComponent(TradeOperationEditor).vm.$emit('update:modelValue', [{
      client_key: 'fill-1', stock_code: '600000.SH', stock_name_snapshot: '浦发银行', side: 'buy',
      stock_rule_id: 's', action_rule_id: 'a', price: '10', quantity: '100', amount: '1000',
      fee: '0', operated_at: '2026-10-23T10:00:00', note: null, display_order: 1,
      compliance_status: 'complied', selection_facts: { is_st: false },
    }])
    await flushPromises()
    await wrapper.findAll('button').find(node => node.text() === '提交当日记录')!.trigger('click')
    await flushPromises()
    const payload = api.submit.mock.calls[0][0]
    expect(payload.expected_account_revision).toBe(1)
    expect(payload.events[0]).toMatchObject({ event_id: 'fill-1', rule_id: 'r', amount_mode: 'auto' })
    expect(payload).not.toHaveProperty('assessment')
    expect(payload.events[0]).not.toHaveProperty('compliance_status')
    expect(payload.events[0]).not.toHaveProperty('selection_facts')
    wrapper.unmount()
  })
  it('历史日只读，保存失败保留草稿以便重试', async () => {
    api.context.mockResolvedValue(context({ can_edit: false, latest_trade_date: '2026-10-24' }))
    const historical = mountWorkspace()
    await flushPromises()
    expect(historical.text()).toContain('历史记录只读')
    expect(historical.findAll('button').some(node => node.text() === '提交当日记录')).toBe(false)
    historical.unmount()
    api.context.mockResolvedValue(context())
    api.submit.mockRejectedValue(new Error('并发冲突'))
    const wrapper = mountWorkspace()
    await flushPromises()
    wrapper.findAllComponents({ name: 'ElInput' }).at(-1)!.vm.$emit('update:modelValue', '保留复盘内容')
    await flushPromises()
    await wrapper.findAll('button').find(node => node.text() === '提交当日记录')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('并发冲突')
    expect((wrapper.vm as unknown as { isDirty: () => boolean }).isDirty()).toBe(true)
    wrapper.unmount()
  })
})
