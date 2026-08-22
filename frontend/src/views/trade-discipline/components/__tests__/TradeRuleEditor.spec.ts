// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import TradeRuleEditor from '@/views/trade-discipline/components/TradeRuleEditor.vue'

const api = vi.hoisted(() => ({
  get: vi.fn(), open: vi.fn(), save: vi.fn(), discard: vi.fn(), publish: vi.fn(),
  archive: vi.fn(), restore: vi.fn(), copy: vi.fn(), remove: vi.fn(),
}))

vi.mock('@/api/tradeDiscipline', () => ({
  getTradeDisciplineRule: (...args: unknown[]) => api.get(...args),
  openTradeDisciplineRuleDraft: (...args: unknown[]) => api.open(...args),
  saveTradeDisciplineRuleDraft: (...args: unknown[]) => api.save(...args),
  discardTradeDisciplineRuleDraft: (...args: unknown[]) => api.discard(...args),
  publishTradeDisciplineRule: (...args: unknown[]) => api.publish(...args),
  archiveTradeDisciplineRule: (...args: unknown[]) => api.archive(...args),
  restoreTradeDisciplineRule: (...args: unknown[]) => api.restore(...args),
  copyTradeDisciplineRule: (...args: unknown[]) => api.copy(...args),
  deleteTradeDisciplineRule: (...args: unknown[]) => api.remove(...args),
}))

function draft(revision = 2) {
  return {
    rule_id: 'rule-1', draft_revision: revision, name: '趋势纪律', capital: '100000',
    source_version_no: 1,
    stock_rules: [
      { detail_id: 's1', name: '突破', max_capital: '40000', content: '第一行\n第二行', display_order: 1, enabled: true },
      { detail_id: 's2', name: '回踩', max_capital: '30000', content: '等待确认', display_order: 2, enabled: false },
    ],
    action_rules: [
      { detail_id: 'a1', name: '建仓', action_type: 'buy', action_subtype: 'open_position', content: '买入', display_order: 1, enabled: true },
      { detail_id: 'a2', name: '清仓', action_type: 'sell', action_subtype: 'liquidate', content: '卖出', display_order: 2, enabled: true },
    ],
  }
}

function detail() {
  return {
    id: 'rule-1', name: '趋势纪律', status: 'active', latest_version_no: 1,
    draft_revision: 2, proposed_name: '趋势纪律', management_status: 'active',
    latest_management_event: null, has_pending_management_action: false,
    effective_status: 'active', effective_event_seq: 1, effective_from_trade_date: '2026-08-21',
    effective_version: { ...draft(), version_no: 1 },
    latest_version: { ...draft(), version_no: 1 }, draft: draft(),
  }
}

async function mountEditor() {
  const wrapper = mount(TradeRuleEditor, {
    props: { ruleId: 'rule-1', tradeDate: '2026-08-21', canManage: true },
    global: { plugins: [ElementPlus], directives: { permission: {} } },
  })
  await flushPromises()
  return wrapper
}

function field(wrapper: ReturnType<typeof mount>, label: string) {
  const item = wrapper.findAll('.el-form-item').find((node) => node.text().includes(label))
  if (!item) throw new Error(`missing field: ${label}`)
  return item
}

describe('TradeRuleEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.get.mockResolvedValue(detail())
    api.save.mockImplementation(async (_id, payload) => ({ ...draft(payload.expected_revision + 1), ...payload }))
  })

  it('保存时保留换行、启用态和调整后的展示顺序', async () => {
    const wrapper = await mountEditor()
    await wrapper.get('[aria-label="下移选股规则"]').trigger('click')
    const textareas = wrapper.findAll('textarea')
    await textareas[0].setValue('第一行\n\n第三行')
    await wrapper.get('.rule-editor__footer .el-button:nth-last-child(2)').trigger('click')
    await flushPromises()

    const payload = api.save.mock.calls[0][1]
    expect(payload.expected_revision).toBe(2)
    expect(payload.stock_rules.map((item: any) => item.detail_id)).toEqual(['s2', 's1'])
    expect(payload.stock_rules[0].enabled).toBe(false)
    expect(payload.stock_rules[0].content).toBe('第一行\n\n第三行')
  })

  it('未保存三选明确提供三个动作，并按继续、放弃和保存结果返回', async () => {
    const wrapper = await mountEditor()
    await field(wrapper, '规则名称').get('input').setValue('临时名称')
    const continueResult = (wrapper.vm as any).requestLeave()
    await flushPromises()
    await wrapper.get('.el-dialog__footer .el-button:first-child').trigger('click')
    expect(await continueResult).toBe(false)
    expect((wrapper.vm as any).isDirty()).toBe(true)

    const discardResult = (wrapper.vm as any).requestLeave()
    await flushPromises()
    const buttons = wrapper.findAll('.el-dialog__footer .el-button')
    expect(buttons.map((button) => button.text())).toEqual(['继续编辑', '放弃修改', '保存草稿'])
    await buttons[1].trigger('click')
    expect(await discardResult).toBe(true)
    expect((wrapper.vm as any).isDirty()).toBe(false)
    expect(field(wrapper, '规则名称').get('input').element.value).toBe('趋势纪律')

    await field(wrapper, '规则名称').get('input').setValue('保存后离开')
    const saveResult = (wrapper.vm as any).requestLeave()
    await flushPromises()
    await wrapper.findAll('.el-dialog__footer .el-button')[2].trigger('click')
    expect(await saveResult).toBe(true)
    expect(api.save).toHaveBeenCalledWith('rule-1', expect.objectContaining({
      name: '保存后离开', expected_revision: 2,
    }))
  })

  it('保存并启用先保存当前修改，再使用新修订号发布', async () => {
    api.publish.mockResolvedValue({ changed: true, rule_id: 'rule-1', version_no: 2, effective_from_trade_date: '2026-08-24' })
    const wrapper = await mountEditor()
    await field(wrapper, '规则名称').get('input').setValue('趋势纪律 v2')
    await wrapper.get('.rule-editor__footer .el-button:last-child').trigger('click')
    await flushPromises()

    expect(api.save).toHaveBeenCalledTimes(1)
    expect(api.publish).toHaveBeenCalledWith('rule-1', 3)
    expect(api.get).toHaveBeenCalledTimes(2)
  })

  it('放弃已保存草稿后重新读取双状态详情', async () => {
    api.discard.mockResolvedValue({})
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce('confirm' as any)
    const wrapper = await mountEditor()
    const discardButton = wrapper.findAll('.rule-editor__footer .el-button')
      .find((button) => button.text() === '放弃草稿')!
    await discardButton.trigger('click')
    await flushPromises()

    expect(api.discard).toHaveBeenCalledWith('rule-1')
    expect(api.get).toHaveBeenCalledTimes(2)
  })

  it('复制时明确区分草稿与正式版本来源', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm')
    api.copy.mockResolvedValue({ id: 'rule-copy' })
    const wrapper = await mountEditor()

    confirm.mockResolvedValueOnce('confirm' as any)
    await wrapper.get('.rule-editor__commands .el-button:first-child').trigger('click')
    await flushPromises()
    expect(api.copy).toHaveBeenLastCalledWith('rule-1', 'draft')

    confirm.mockRejectedValueOnce('cancel')
    await wrapper.get('.rule-editor__commands .el-button:first-child').trigger('click')
    await flushPromises()
    expect(api.copy).toHaveBeenLastCalledWith('rule-1', 'published')
  })

  it('快速切换规则时忽略迟到的旧详情响应', async () => {
    let resolveFirst!: (value: ReturnType<typeof detail>) => void
    api.get
      .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce({
        ...detail(),
        id: 'rule-2',
        name: '第二条规则',
        draft: { ...draft(), rule_id: 'rule-2', name: '第二条规则' },
      })
    const wrapper = mount(TradeRuleEditor, {
      props: { ruleId: 'rule-1', tradeDate: '2026-08-21', canManage: true },
      global: { plugins: [ElementPlus], directives: { permission: {} } },
    })
    await wrapper.setProps({ ruleId: 'rule-2' })
    await flushPromises()
    resolveFirst(detail())
    await flushPromises()

    expect(wrapper.get('.app-section-title').text()).toBe('第二条规则')
  })
})
