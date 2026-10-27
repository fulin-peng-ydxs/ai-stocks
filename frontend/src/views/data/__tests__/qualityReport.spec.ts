import { describe, expect, it } from 'vitest'
import { checkupSummaryText, qualityDetailText, intradayRecoveryAction } from '../qualityReport'
import { ISSUE_LAYER, ISSUE_TYPES_ACTIVE, sortQualityIssueTypes, RECOVER_ACTION_LABEL, taskDisplayLabel } from '@/api/data'

describe('体检摘要业务文案', () => {
  const summary = (detail: string, name = '分时监控范围覆盖') => checkupSummaryText({
    name, detail, ok: true, status: 'warn',
  })
  it('兼容历史 Python 字典和 JSON，数量为零也保留，按业务顺序展示', () => {
    for (const detail of [
      "{'intraday_invalid': 0, 'intraday_partial': 42, 'intraday_gap': 5216}",
      '{"intraday_gap":5216,"intraday_partial":42,"intraday_invalid":0}',
    ]) {
      expect(summary(detail)).toBe('整日缺失 5,216 项 · 分钟不完整 42 项 · 数据非法 0 项')
    }
  })
  it.each([
    '{bad', '{}', '{"intraday_gap":1}',
    '{"intraday_gap":-1,"intraday_partial":0,"intraday_invalid":0}',
    '{"intraday_gap":"1","intraday_partial":0,"intraday_invalid":0}',
    '{"intraday_gap":1.5,"intraday_partial":0,"intraday_invalid":0}',
    '{"intraday_gap":1,"intraday_partial":0,"intraday_invalid":0,"extra":1}',
  ])('无法识别的历史统计提示重新检查，不显示内部对象：%s', detail => {
    expect(summary(detail)).toBe('历史统计格式无法识别，请重新运行结构体检')
  })
  it('保留业务文案及其他检查说明，不把普通说明误判为字典', () => {
    expect(summary('监控范围暂无分时质量问题')).toBe('监控范围暂无分时质量问题')
    expect(summary('异常股票交易日 1 项', '分钟结构与价格量额')).toBe('异常股票交易日 1 项')
  })
})

describe('股本市值质量诊断', () => {
  it('兼容既有纯文本和板块消息', () => {
    expect(qualityDetailText('历史缺失')).toBe('历史缺失')
    expect(qualityDetailText('{bad')).toContain('诊断格式暂不支持')
    expect(qualityDetailText('{"message":"板块缺失","periods":["即时"]}')).toBe('板块缺失')
  })
  it('展示核验范围、价格证据和来源失败，不把请求成功当修好', () => {
    const text = qualityDetailText(JSON.stringify({ message: '不一致，仍待处理', last_collection: {
      date_start: '2017-01-01 00:00:00', date_end: '2026-10-16 00:00:00', diagnostics: {
        errors: ['timeout'], remaining: { total_mv_price_basis_mismatch: { evidence: [
          { trade_date: '2018-01-23', raw_close: 16.5, valuation_close: 16.49 },
        ] } },
      },
    } }))
    expect(text).toContain('不一致，仍待处理')
    expect(text).toContain('2017-01-01~2026-10-16')
    expect(text).toContain('本地收盘 16.5，市值源收盘 16.49')
    expect(text).toContain('来源请求失败')
  })
  it('诊断样例有界并支持精度及披露日期', () => {
    const text = qualityDetailText(JSON.stringify({ message: '缺失', last_collection: {
      date_start: '2017-01-01', date_end: '2017-12-31', diagnostics: { remaining: {
        gap: { evidence: Array.from({ length: 20 }, (_, i) => ({ trade_date: `D${i}`, effective_date: 'E', available_date: 'A' })) },
      } },
    } }))
    expect(text).toContain('D2：生效 E，披露 A')
    expect(text).not.toContain('D3：')
  })
  it('历史日线缺口接入质量层和修复入口', () => {
    expect(ISSUE_TYPES_ACTIVE).toContain('history_data_gap')
    expect(ISSUE_LAYER.history_data_gap).toBe('L4')
    expect(RECOVER_ACTION_LABEL.history_data_gap).toContain('全历史')
  })
  it('原始来源异常不再作为活动业务类型，历史记录仍可识别', () => {
    expect(ISSUE_TYPES_ACTIVE).not.toContain('capital_raw_invalid')
    expect(ISSUE_LAYER.capital_raw_invalid).toBe('来源')
  })
  it('三类问题都可筛选、显示层次并创建修复任务', () => {
    for (const type of ['capital_gap', 'capital_invalid', 'capital_mismatch']) {
      expect(ISSUE_TYPES_ACTIVE).toContain(type)
      expect(ISSUE_LAYER[type]).toBe('L2')
      expect(RECOVER_ACTION_LABEL[type]).toContain('复检')
      expect(taskDisplayLabel('fix', { issue_type: type })).toContain('股本市值')
    }
  })
})

describe('质量诊断缺字段与未知结构', () => {
  it.each([
    '{"message":"缺失","last_collection":{}}',
    '{"message":"分钟不完整","coverage":{"trade_date":"2026-10-08"}}',
  ])('缺失值保持未记录，不显示运行时占位：%s', detail => {
    const text = qualityDetailText(detail)
    expect(text).toContain('未记录')
    expect(text).not.toMatch(/undefined|None|NaN|\[object Object\]/)
  })
  it.each(['{"unexpected_count":3}', 'null', '[1,2]', '{bad'])('未知诊断不原样展示为 JSON：%s', detail => {
    expect(qualityDetailText(detail)).toContain('诊断格式暂不支持')
  })
  it('来源异常在业务摘要说明失败，原始字符串仍可供技术详情读取', () => {
    const raw = JSON.stringify({ message: '分钟不完整', coverage: { covered_count: 0, required_count: 238 },
      availability: { sources: [{ source: 'ths', outcome: 'error', failure_reason: 'HTTPError: 502 https://example.test' }] } })
    const text = qualityDetailText(raw)
    expect(text).toContain('0/238')
    expect(text).toContain('同花顺最近请求失败')
    expect(text).not.toContain('HTTPError')
    expect(JSON.parse(raw).availability.sources[0].failure_reason).toContain('HTTPError')
  })
})

describe('质量类型排序', () => {
  it('服务端乱序子集按业务归类，保留未知与历史类型且不修改输入', () => {
    const types = ['capital_gap', 'board_fund_missing', 'mv_gap', 'data_gap', 'capital_raw_invalid', 'future_type']
    expect(sortQualityIssueTypes(types)).toEqual([
      'capital_gap', 'board_fund_missing', 'mv_gap', 'data_gap', 'capital_raw_invalid', 'future_type',
    ])
    expect(types[0]).toBe('capital_gap')
    expect(sortQualityIssueTypes([])).toEqual([])
  })
})

describe('分时覆盖与来源证据', () => {
  it('同花顺修复证据使用中文来源名', () => {
    const text = qualityDetailText(JSON.stringify({ message: '缺口已补采', availability: {
      sources: [{ source: 'ths', first: '2026-08-18 09:30:00', last: '2026-10-20 15:00:00' }],
    } }))
    expect(text).toContain('同花顺上次有效响应')
    expect(text).not.toContain('ths上次有效响应')
  })
  it('展示缺失时段、响应范围和未改善结果，不输出原始 JSON', () => {
    const text = qualityDetailText(JSON.stringify({
      message: '分时分钟不完整，有效81点',
      coverage: { covered_count: 81, required_count: 238, missing_ranges: ['09:31–11:30', '13:01–13:37'] },
      availability: { reason: '当前来源未覆盖缺失分钟', sources: [{ source: 'sina', first: '2026-10-08 13:49:00', last: '2026-10-20 15:00:00', observed_at: '2026-10-20T15:43:47+08:00' }] },
      last_repair: { outcome: 'unavailable', before_points: 81, after_points: 81 },
    }))
    expect(text).toContain('81/238')
    expect(text).toContain('09:31–11:30、13:01–13:37')
    expect(text).toContain('新浪上次有效响应 2026-10-08 13:49:00')
    expect(text).toContain('2026-10-20 15:43:47')
    expect(text).toContain('当前来源无法覆盖，归档 81→81 点')
    expect(text).not.toContain('"coverage"')
  })
  it('失败尝试与旧有效窗口分别说明，不把旧窗口当成本次成功', () => {
    const text = qualityDetailText(JSON.stringify({ message: '不完整', availability: { sources: [{
      source: 'sina', outcome: 'error', failure_reason: 'TimeoutError', checked_at: '2026-10-20T16:00:00+08:00',
    }] } }))
    expect(text).toContain('新浪最近请求失败：详见关联任务日志')
    expect(text).not.toContain('TimeoutError')
    expect(text).not.toContain('上次有效响应')
  })
})


it('分时恢复动作消费后端可修复性，其他质量类型保持原入口', () => {
  const issue = { issue_type: 'intraday_partial', intraday: { can_repair: false, reason: '缺失早盘' } } as any
  expect(intradayRecoveryAction(issue)).toMatchObject({ label: '重新核验', recheck: true })
  issue.intraday.can_repair = true
  expect(intradayRecoveryAction(issue)).toMatchObject({ label: '补采复检', recheck: false })
  issue.intraday = { status: 'deferred', can_repair: false, reason: '16:15后可复查' }
  expect(intradayRecoveryAction(issue)?.tooltip).toContain('16:15后可复查')
  expect(intradayRecoveryAction(issue)?.tooltip).toContain('立即请求')
  expect(intradayRecoveryAction({ issue_type: 'capital_gap' } as any)).toBeNull()
})
