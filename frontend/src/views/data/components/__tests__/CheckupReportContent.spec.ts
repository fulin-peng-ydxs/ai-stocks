// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ElementPlus from 'element-plus'
import CheckupReportContent from '../CheckupReportContent.vue'
import type { CheckupCheck, CheckupReport, CheckupIssueItem, QualityIssue } from '@/api/data'
import { checkupDetailGroups, checkupIssueFilters, orderedCheckupItems, visibleQualityRows } from '../../qualityReport'

const item: CheckupIssueItem = {
  code: '309265', name: '2026一季报预增', issue_type: 'board_fund_missing',
  target_date: '2026-10-13', missing_periods: ['即时', '20日'], status: 'ignored',
}
const report = (check: CheckupCheck): CheckupReport => ({
  all_ok: true, passed: 0, total: 1, warning_count: 1, fails: [],
  groups: [{ group: 'E. 板块数据', checks: [check] }],
})
const render = (value: CheckupReport) => mount(CheckupReportContent, {
  props: { report: value }, global: { plugins: [ElementPlus] },
})
const check = (): CheckupCheck => ({
  name: '板块资金流目标日五周期齐全', status: 'warn', ok: true,
  detail: '0 个待处理 · 1 个已忽略', items: [item],
})

describe('体检报告展示与台账定位', () => {
  it('默认收起多对象明细，展开后逐项显示状态并发出精确定位事件', async () => {
    const wrapper = render(report(check()))
    expect(wrapper.text()).toContain('0 个待处理 · 1 个已忽略')
    expect(wrapper.find('.checkup-detail-group').exists()).toBe(false)
    const trigger = wrapper.get('.app-summary-disclosure-card__summary')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    await trigger.trigger('click')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('.checkup-detail-group').text()).toContain('即时、20日')
    const link = wrapper.get('a.el-link')
    expect(link.attributes('href')).toContain('code=309265')
    await link.trigger('click')
    expect(wrapper.emitted('locate')?.[0]).toEqual([item])
  })

  it('兼容旧任务长说明，保留全文但默认不撑高行', async () => {
    const legacy = { ...check(), items: undefined, detail: '历史检查说明。'.repeat(40) }
    const wrapper = render(report(legacy))
    expect(wrapper.get('.app-summary-disclosure-card__preview').text()).toBe(`${legacy.detail.slice(0, 100)}…`)
    expect(wrapper.find('.checkup-description').exists()).toBe(false)
    await wrapper.get('.app-summary-disclosure-card__summary').trigger('click')
    expect(wrapper.get('.checkup-description').text()).toBe(legacy.detail)
  })

  it('短说明不增加展开操作，空报告有明确反馈', () => {
    const wrapper = render(report({ name: '无孤儿', ok: true, detail: '孤儿 0' }))
    expect(wrapper.find('button.app-summary-disclosure-card__summary').exists()).toBe(false)
    expect(wrapper.text()).toContain('通过')
    const empty = render({ ...report(check()), groups: [] })
    expect(empty.text()).toContain('暂无体检明细')
  })

  it.each(['warn', 'fail'] as const)('短说明的 %s 也能展开，展示检查依据和处置说明', async (status) => {
    const wrapper = render(report({
      name: '个股行情覆盖至结果日期', ok: status === 'warn', status,
      detail: '目标日未覆盖 100 条', help: '核对停牌与采集缺口后复检。',
      evidence: [{
        label: '命中记录', total: 100, limit: 20,
        columns: [{ key: 'code', label: '股票代码' }, { key: 'as_of_date', label: '结果日期' }],
        rows: [{ code: '600001.SH', as_of_date: '2026-10-13' }],
      }],
    }))
    const trigger = wrapper.get('.app-summary-disclosure-card__summary')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    await trigger.trigger('click')
    expect(wrapper.get('.checkup-detail-group').text()).toContain('共 100 条，展示 1 条样例')
    expect(wrapper.findAll('.app-data-table')).toHaveLength(1)
    expect(wrapper.get('.checkup-detail-group').text()).toContain('600001.SH')
    expect(wrapper.get('.checkup-help').text()).toContain('核对停牌与采集缺口后复检')
    expect(wrapper.find('a.el-link').exists()).toBe(false)
  })

  it('整体状态与旧报告都有展开反馈，说明不能伪装成异常对象', async () => {
    const wrapper = render(report({
      name: '暂无行情基准日', ok: true, status: 'warn', detail: '无法判断覆盖',
      help: '先完成市场行情采集后重检。', evidence: [],
    }))
    await wrapper.get('.app-summary-disclosure-card__summary').trigger('click')
    expect(wrapper.text()).toContain('先完成市场行情采集后重检')
    expect(wrapper.text()).toContain('本项为整体状态检查')
    expect(wrapper.find('.checkup-detail-group').exists()).toBe(false)
    await wrapper.setProps({ report: report({ name: '旧检查', ok: false, detail: '缺失 1' }) })
    const trigger = wrapper.get('.app-summary-disclosure-card__summary')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    await trigger.trigger('click')
    expect(wrapper.text()).toContain('该历史报告未保存逐条明细')
  })

  it('有明细的长说明展开后仍保留全文，通过项的额外说明也可查看', async () => {
    const detail = '需要核对的完整依据。'.repeat(20)
    const wrapper = render(report({ ...check(), detail }))
    await wrapper.get('.app-summary-disclosure-card__summary').trigger('click')
    expect(wrapper.get('.checkup-description').text()).toBe(detail)
    await wrapper.setProps({ report: report({
      name: '全历史市值关系', ok: true, detail: '异常 0 行', help: '全历史与台账时间范围不同。',
    }) })
    await wrapper.get('.app-summary-disclosure-card__summary').trigger('click')
    expect(wrapper.get('.checkup-help').isVisible()).toBe(true)
    expect(wrapper.get('.checkup-help').text()).toContain('全历史与台账时间范围不同')
  })

  it('定位清除无关筛选，已忽略对象不被隐藏已办偏好过滤', () => {
    expect(checkupIssueFilters(item)).toEqual({
      code: '309265', issue_type: ['board_fund_missing'], severity: [], status: ['ignored'],
    })
    const rows = [{ status: 'ignored' }, { status: 'open' }, { status: 'resolved' }] as QualityIssue[]
    expect(visibleQualityRows(rows, true, ['ignored'])).toEqual(rows.slice(0, 2))
    expect(visibleQualityRows(rows, true, [])).toEqual([rows[1]])
    expect(checkupIssueFilters({ ...item, status: 'unrecorded' }).status).toEqual([])
    const pending = { ...item, code: '309274', status: 'open' as const }
    const original = [item, pending]
    expect(orderedCheckupItems(original)).toEqual([pending, item])
    expect(original).toEqual([item, pending])
  })
})


describe('体检展开内容统一行列模型', () => {
  it('板块对象和 SQL 样例共用表格结构，保留日期、状态与原始定位对象', () => {
    const value: CheckupCheck = {
      ...check(), items: [item, { ...item, code: '309274', target_date: '2026-10-14', status: 'open' }],
      evidence: [{
        label: '检查依据', total: 50, limit: 20,
        columns: [{ key: 'code', label: '代码' }, { key: 'trade_date', label: '交易日' },
          { key: 'quality', label: '质量' }, { key: 'adj_factor', label: '复权因子' }],
        rows: [{ code: '600001.SH', trade_date: '2026-10-13', quality: '缺失', adj_factor: '1' }],
      }],
    }
    const original = JSON.stringify(value)
    const groups = checkupDetailGroups(value)
    expect(groups).toHaveLength(2)
    expect(groups[0].columns.map(x => x.key)).toEqual(['object', 'status', 'gap', 'target_date'])
    expect(groups[0].context).toBeUndefined()
    expect(groups[0].rows[0].issue?.status).toBe('open')
    expect(groups[0].rows[1].issue).toBe(item)
    expect(groups[1].columns.map(x => x.role)).toEqual(['code', 'date', 'status', 'number'])
    expect(groups[1].total).toBe(50)
    expect(JSON.stringify(value)).toBe(original)
    expect(checkupDetailGroups(check())[0].context).toBe('基准日 2026-10-13')
  })
})
