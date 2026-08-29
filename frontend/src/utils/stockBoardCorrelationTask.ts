export type StockBoardCorrelationScope = 'all' | 'selected'

export interface StockBoardCorrelationTaskForm {
  scope: StockBoardCorrelationScope
  codes: string[]
  force: boolean
}

export function createStockBoardCorrelationTaskForm(
  patch: Partial<StockBoardCorrelationTaskForm> = {},
): StockBoardCorrelationTaskForm {
  return { scope: 'all', codes: [], force: false, ...patch }
}

export function buildStockBoardCorrelationTaskParams(
  form: StockBoardCorrelationTaskForm,
): { params?: Record<string, unknown>; error?: string } {
  if (form.scope === 'selected' && !form.codes.length) {
    return { error: '指定股票范围时请至少选择一只股票' }
  }
  const params: Record<string, unknown> = { force: form.force }
  if (form.scope === 'selected') params.codes = [...form.codes]
  return { params }
}

export function stockBoardCorrelationTaskFormFromParams(
  params: Record<string, unknown> | null | undefined,
): StockBoardCorrelationTaskForm {
  const codes = Array.isArray(params?.codes) ? params.codes.map(String) : []
  return createStockBoardCorrelationTaskForm({
    scope: codes.length ? 'selected' : 'all',
    codes,
    force: params?.force === true,
  })
}
