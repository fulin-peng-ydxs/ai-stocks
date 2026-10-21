// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import type { QualityIssue } from '@/api/data'
import AppJsonViewer from '@/components/AppJsonViewer.vue'
import QualityDiagnosticContent from '../QualityDiagnosticContent.vue'
import { qualityDiagnostic } from '../../qualityDiagnostic'

const issue = { id: 168525, code: '000737.SZ', issue_type: 'intraday_partial', status: 'open', trade_date: '2026-10-08',
  detail: JSON.stringify({ message: '分时分钟不完整，有效 178 点',
    coverage: { trade_date: '2026-10-08', point_count: 178, covered_count: 178, required_count: 238,
      missing_ranges: ['09:31–10:30'], missing_times: ['09:31'] },
    diagnostics: { invalid_rows: 0, off_session_rows: 0, duplicate_rows: 0 },
    availability: { status: 'needs_verification', reason: '不应重复展示的长段汇总',
      decisions: [{ source: 'sina', request: true, reason: '尚无有效取源证据，需核验' },
        { source: 'eastmoney', request: false, reason: '目标日不在近 5 交易日范围' }],
      sources: [{ source: 'sina', outcome: 'error', failure_reason: 'HTTPError 502', checked_at: '2026-10-20T17:00:00+08:00' }] },
    last_repair: { outcome: 'unchanged', before_points: 178, after_points: 178, checked_at: '2026-10-20T17:01:00+08:00' },
  }) } as QualityIssue

describe('质量诊断详情', () => {
  it('分区展示覆盖、来源和复检，原始数据默认收起且可完整查看', async () => {
    const original = issue.detail
    const wrapper = mount(QualityDiagnosticContent, { props: { issue }, global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.text()).toContain('178 / 238 点')
    expect(wrapper.text()).toContain('09:31–10:30')
    expect(wrapper.text()).toContain('非法记录0 条')
    expect(wrapper.text()).toContain('来源核验')
    expect(wrapper.text()).toContain('目标日不在近 5 交易日范围')
    expect(wrapper.text()).toContain('未改善')
    expect(wrapper.text()).not.toContain('不应重复展示的长段汇总')
    expect(wrapper.findComponent(AppJsonViewer).exists()).toBe(false)
    await wrapper.get('button.app-summary-disclosure-card__summary').trigger('click')
    await flushPromises()
    expect(wrapper.findComponent(AppJsonViewer).props('source')).toBe(original)
    expect(wrapper.text()).toContain('问题类型编码intraday_partial')
    await wrapper.setProps({ issue: { ...issue, id: 2, detail: '旧版本诊断文本' } })
    expect(wrapper.findComponent(AppJsonViewer).exists()).toBe(false)
    expect(wrapper.text()).toContain('旧版本诊断文本')
    expect(issue.detail).toBe(original)
    wrapper.unmount()
  })
  it('缺字段或接口异常不能解释为零覆盖，也不把技术错误放进业务原因', () => {
    const result = qualityDiagnostic({ ...issue, detail: JSON.stringify({ coverage: { trade_date: issue.trade_date },
      availability: { sources: [{ source: 'sina', outcome: 'error', failure_reason: 'HTTPError: 502' }],
        decisions: [{ source: 'sina', request: true, reason: '最近请求失败：HTTPError: 502' }] } }) })
    expect(result.coverageFields[0].value).toBe('未记录')
    expect(result.sources[0].points).toBe('未记录')
    expect(result.sources[0].reason).toContain('最近请求失败')
    expect(result.sources[0].reason).not.toContain('HTTPError')
    expect(result.sources[0].range).toBe('未记录有效响应范围')
  })
  it('非分时诊断及未知数据不套用分钟解释，缺失分钟为零时仍明确显示无缺失', () => {
    expect(qualityDiagnostic({ ...issue, issue_type: 'other', detail: issue.detail }).structured).toBe(false)
    const result = qualityDiagnostic({ ...issue, detail: JSON.stringify({ coverage: {
      covered_count: 0, required_count: 238, point_count: 0, missing_times: [],
    } }) })
    expect(result.coverageFields[0].value).toBe('0 点')
    expect(result.coverageFields.find(field => field.label === '缺失时段')?.value).toBe('无')
  })
})
