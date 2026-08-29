import { describe, expect, it } from 'vitest'
import {
  buildStockBoardCorrelationTaskParams,
  createStockBoardCorrelationTaskForm,
  stockBoardCorrelationTaskFormFromParams,
} from '../stockBoardCorrelationTask'

describe('stockBoardCorrelationTask', () => {
  it('全市场默认只提交显式 force=false', () => {
    expect(buildStockBoardCorrelationTaskParams(createStockBoardCorrelationTaskForm()))
      .toEqual({ params: { force: false } })
  })

  it('指定股票必须非空并原样提交代码与 force', () => {
    expect(buildStockBoardCorrelationTaskParams(createStockBoardCorrelationTaskForm({
      scope: 'selected', codes: [], force: false,
    }))).toEqual({ error: '指定股票范围时请至少选择一只股票' })
    expect(buildStockBoardCorrelationTaskParams(createStockBoardCorrelationTaskForm({
      scope: 'selected', codes: ['600000.SH', '000001.SZ'], force: true,
    }))).toEqual({
      params: { codes: ['600000.SH', '000001.SZ'], force: true },
    })
  })

  it('编辑调度时按 params 回显范围、代码和强制重算', () => {
    expect(stockBoardCorrelationTaskFormFromParams({
      codes: ['600000.SH'], force: true,
    })).toEqual({ scope: 'selected', codes: ['600000.SH'], force: true })
    expect(stockBoardCorrelationTaskFormFromParams({ force: false }))
      .toEqual({ scope: 'all', codes: [], force: false })
  })
})
