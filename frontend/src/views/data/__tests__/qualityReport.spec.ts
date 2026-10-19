import { describe, expect, it } from 'vitest'
import { qualityDetailText } from '../qualityReport'
import { ISSUE_LAYER, ISSUE_TYPES_ACTIVE, sortQualityIssueTypes, RECOVER_ACTION_LABEL, taskDisplayLabel } from '@/api/data'

describe('股本市值质量诊断', () => {
  it('兼容既有纯文本和板块消息', () => {
    expect(qualityDetailText('历史缺失')).toBe('历史缺失')
    expect(qualityDetailText('{bad')).toBe('{bad')
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

describe('质量类型排序', () => {
  it('服务端乱序子集按业务归类，保留未知与历史类型且不修改输入', () => {
    const types = ['capital_gap', 'board_fund_missing', 'mv_gap', 'data_gap', 'capital_raw_invalid', 'future_type']
    expect(sortQualityIssueTypes(types)).toEqual([
      'data_gap', 'mv_gap', 'capital_gap', 'board_fund_missing', 'capital_raw_invalid', 'future_type',
    ])
    expect(types[0]).toBe('capital_gap')
    expect(sortQualityIssueTypes([])).toEqual([])
  })
})
