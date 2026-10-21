// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import type { IndicatorDef, ScoreProfileVersion } from '@/api/scoreProfile'
import type { TradeProfileVersion } from '@/api/tradeProfile'
import ProfileVersionContent from '../ProfileVersionContent.vue'
import AppJsonViewer from '@/components/AppJsonViewer.vue'
import { conditionRelation, conditionVersionRows, scoreVersionRows } from '../profileVersionDetails'

const definitions = [{ key: 'price_signal', name_cn: '价格信号',
  params: [{ name: 'period', label: '观察周期', default: 99, unit: '日' }] }] as IndicatorDef[]
const score: ScoreProfileVersion = { version: 1, name: '历史评分', saved_at: '2026-10-20',
  include_st: false, grade_thresholds: { A: 80 }, items: [{ indicator: 'price_signal',
    enabled: false, params: { period: 10 }, weight: 0, scoring: { type: 'linear', min: 0, max: 100 } }] }
const trade: TradeProfileVersion = { version: 2, name: '历史买卖', saved_at: '2026-10-20',
  buy_tree: { op: 'OR', children: [{ indicator: 'price_signal', params: { period: 5 }, cmp: '==', value: true }] },
  sell_tree: {}, backstop: { take_profit: 0, stop_loss: 0.05, max_hold_days: 10 } }
const render = (version: ScoreProfileVersion | TradeProfileVersion) => mount(ProfileVersionContent, {
  props: { version, definitions }, global: { plugins: [ElementPlus] },
})

describe('方案历史版本业务展示', () => {
  it('评分先显示保存的名称、参数、停用和零权重，原始配置默认收起且不修改原对象', async () => {
    const before = JSON.stringify(score)
    const wrapper = render(score)
    await flushPromises()
    expect(wrapper.text()).toContain('价格信号')
    expect(wrapper.text()).toContain('观察周期 10日')
    expect(wrapper.text()).toContain('停用')
    expect(wrapper.text()).toContain('0%')
    expect(wrapper.text()).not.toContain('99')
    expect(wrapper.text()).not.toContain('"indicator"')
    await wrapper.get('button.app-summary-disclosure-card__summary').trigger('click')
    expect(wrapper.findComponent(AppJsonViewer).props('source')).toBe(JSON.stringify(score))
    expect(JSON.stringify(score)).toBe(before)
  })
  it('买卖关系和兜底规则以业务值展示，换版本关闭原始配置', async () => {
    const wrapper = render(trade)
    await flushPromises()
    expect(wrapper.text()).toContain('任一启用条件满足')
    expect(wrapper.text()).toContain('等于 是')
    expect(wrapper.text()).toContain('未设置条件')
    expect(wrapper.text()).toContain('止盈0%')
    expect(wrapper.text()).toContain('止损5%')
    expect(wrapper.text()).toContain('最长持有10 个交易日')
    await wrapper.get('button.app-summary-disclosure-card__summary').trigger('click')
    await wrapper.setProps({ version: score })
    expect(wrapper.get('button.app-summary-disclosure-card__summary').attributes('aria-expanded')).toBe('false')
  })
  it('未登记的历史指标和比较方式保留记录但不充当业务名称', () => {
    const rows = conditionVersionRows({ op: 'AND', children: [
      { indicator: 'retired_signal', cmp: 'internal_compare', value: false },
    ] }, [])
    expect(rows).toHaveLength(1)
    expect(rows[0].name).toBe('未登记指标')
    expect(rows[0].rule).toBe('比较方式未识别 否')
    expect(conditionRelation({})).toBe('未设置条件')
    expect(scoreVersionRows(score, definitions)[0].params).toContain('10日')
  })
  it('历史小数参数不被截成零，百分比转换不引入浮点尾数', () => {
    const version = { ...score, items: [{ ...score.items[0], weight: 0.29, params: { period: 0.000000001 } }] }
    const row = scoreVersionRows(version, definitions)[0]
    expect(row.params).toContain('0.000000001')
    expect(row.weight).toBe('29%')
  })
})
