import { describe, expect, it } from 'vitest'
import { relatedBoardExportValues } from '../relatedBoardExport'
import type { StockRelatedBoards } from '@/types/relatedBoards'

const summary: StockRelatedBoards = {
  as_of_date: '2026-08-28',
  benchmark: { code: '000001.SH', name: '上证指数', fallback: false },
  industry: { board_code: 'I1', name: '银行', score: 0.8, corr_20: 0.8, corr_60: 0.8,
    sample_20: 20, sample_60: 60, confidence: 'high' },
  concept: null,
}

describe('走势结果导出来源', () => {
  it('当前结果输出业务日，历史结果输出各自的真实来源日', () => {
    expect(relatedBoardExportValues(summary, 'industry')).toEqual(['银行', '2026-08-28', '当日'])
    expect(relatedBoardExportValues({ ...summary, industry: { ...summary.industry!, history: {
      as_of_date: '2026-08-25', benchmark: summary.benchmark,
    } } }, 'industry')).toEqual(['银行', '2026-08-25', '历史'])
  })
  it('无结果或摘要不可用时不得泄漏旧名称和日期', () => {
    expect(relatedBoardExportValues(summary, 'concept')).toEqual(['', '', '无结果'])
    expect(relatedBoardExportValues(undefined, 'industry')).toEqual(['', '', '无结果'])
    expect(relatedBoardExportValues({ ...summary, unavailable_reason: 'as_of_mismatch' }, 'industry'))
      .toEqual(['', '', '无结果'])
  })
})
