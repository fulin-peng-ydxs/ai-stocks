/** 手动采集与调度共用分时参数契约。 */
export interface IntradayIngestForm {
  mode: 'update' | 'refetch'
  asset_type: 'all' | 'stock' | 'index'
  scope: 'all' | 'selected'
  codes: string[]
  date_start: string
  date_end: string
}
export function createIntradayIngestForm(params: Record<string, unknown> = {}): IntradayIngestForm {
  const codes = Array.isArray(params.codes) ? params.codes.filter((c): c is string => typeof c === 'string') : []
  return {
    mode: params.mode === 'refetch' ? 'refetch' : 'update',
    asset_type: params.asset_type === 'stock' || params.asset_type === 'index' ? params.asset_type : 'all',
    scope: codes.length ? 'selected' : 'all', codes,
    date_start: typeof params.date_start === 'string' ? params.date_start : '',
    date_end: typeof params.date_end === 'string' ? params.date_end : '',
  }
}
export function buildIntradayIngestParams(form: IntradayIngestForm): {
  params: Record<string, unknown>; error?: string
} {
  const params: Record<string, unknown> = { mode: form.mode }
  if (form.asset_type !== 'all') params.asset_type = form.asset_type
  if (form.scope === 'selected') {
    if (!form.codes.length) return { params, error: '请选择需要采集的个股或指数' }
    params.codes = [...new Set(form.codes)]
  }
  if (form.mode === 'refetch') {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(form.date_start)) return { params, error: '请选择重采起始日期' }
    const end = form.date_end || form.date_start
    if (end < form.date_start) return { params, error: '结束日期不得早于起始日期' }
    params.date_start = form.date_start
    params.date_end = end
  }
  return { params }
}
