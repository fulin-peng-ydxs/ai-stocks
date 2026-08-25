export type StockIngestRecipe =
  | 'daily_update'
  | 'history_backfill'
  | 'range_refetch'
  | 'valuation_history'
  | 'valuation_gaps'
  | 'basic_refresh'
  | 'delisted_history'

export type StockIngestScope = 'all' | 'selected'

export interface StockIngestFormValue {
  recipe: StockIngestRecipe
  scope: StockIngestScope
  codes: string[]
  date_start: string
  date_end: string
  years: number | null
  concurrency: number | null
}

export const STOCK_INGEST_RECIPE_OPTIONS: Array<{
  value: StockIngestRecipe
  label: string
  description: string
  heavy?: boolean
}> = [
  { value: 'daily_update', label: '日常同步', description: '补到最新交易日，包含行情收口、复权和最新市值维护' },
  { value: 'history_backfill', label: '历史行情补全', description: '补指定历史年限的日线行情，适合初始化或大范围缺数', heavy: true },
  { value: 'range_refetch', label: '日期区间重采', description: '覆盖重采指定交易日区间，可限定股票', heavy: true },
  { value: 'valuation_history', label: '市值历史补采', description: '补从未完整采过市值的股票历史数据', heavy: true },
  { value: 'valuation_gaps', label: '市值缺口修复', description: '按已有日线逐股补齐总市值和流通市值缺口', heavy: true },
  { value: 'basic_refresh', label: '基础资料刷新', description: '刷新上市日、退市日和行业，固定全市场' },
  { value: 'delisted_history', label: '退市股历史补全', description: '先刷新基础资料，再补回测窗口内退市股历史', heavy: true },
]

export const STOCK_INGEST_RECIPE_LABEL = Object.fromEntries(
  STOCK_INGEST_RECIPE_OPTIONS.map((item) => [item.value, item.label]),
) as Record<StockIngestRecipe, string>

const CODE_RECIPES = new Set<StockIngestRecipe>([
  'daily_update', 'history_backfill', 'range_refetch', 'valuation_history', 'valuation_gaps',
])
const YEAR_RECIPES = new Set<StockIngestRecipe>([
  'history_backfill', 'valuation_history', 'delisted_history',
])
const CONCURRENCY_RECIPES = new Set<StockIngestRecipe>([
  'daily_update', 'history_backfill', 'range_refetch', 'valuation_history', 'valuation_gaps',
])

export function createStockIngestForm(
  patch: Partial<StockIngestFormValue> = {},
): StockIngestFormValue {
  return {
    recipe: 'daily_update', scope: 'all', codes: [], date_start: '', date_end: '',
    years: null, concurrency: null, ...patch,
  }
}

export function stockIngestSupportsCodes(recipe: StockIngestRecipe): boolean {
  return CODE_RECIPES.has(recipe)
}

export function stockIngestSupportsYears(recipe: StockIngestRecipe): boolean {
  return YEAR_RECIPES.has(recipe)
}

export function stockIngestSupportsConcurrency(recipe: StockIngestRecipe): boolean {
  return CONCURRENCY_RECIPES.has(recipe)
}

export function isHeavyStockIngestRecipe(recipe: StockIngestRecipe): boolean {
  return STOCK_INGEST_RECIPE_OPTIONS.find((item) => item.value === recipe)?.heavy === true
}

export function buildStockIngestParams(
  form: StockIngestFormValue,
): { params?: Record<string, unknown>; error?: string } {
  const params: Record<string, unknown> = { recipe: form.recipe }
  if (stockIngestSupportsCodes(form.recipe) && form.scope === 'selected') {
    if (!form.codes.length) return { error: '指定股票范围时请至少选择一只股票' }
    params.codes = [...form.codes]
  }
  if (form.recipe === 'range_refetch') {
    if (!form.date_start) return { error: '日期区间重采需填写起始日期' }
    if (form.date_end && form.date_end < form.date_start) return { error: '结束日期不得早于起始日期' }
    params.date_start = form.date_start
    params.date_end = form.date_end || form.date_start
  }
  if (stockIngestSupportsYears(form.recipe) && form.years != null) {
    if (!Number.isInteger(form.years) || form.years < 1 || form.years > 30) {
      return { error: '历史年数须为 1–30 的整数' }
    }
    params.years = form.years
  }
  if (stockIngestSupportsConcurrency(form.recipe) && form.concurrency != null) {
    if (!Number.isInteger(form.concurrency) || form.concurrency < 1 || form.concurrency > 16) {
      return { error: '采集并发数须为 1–16 的整数' }
    }
    params.concurrency = form.concurrency
  }
  return { params }
}

export function stockIngestSummary(form: StockIngestFormValue): string {
  const label = STOCK_INGEST_RECIPE_LABEL[form.recipe]
  const scope = stockIngestSupportsCodes(form.recipe) && form.scope === 'selected'
    ? `${form.codes.length || 0} 只指定股票`
    : '全市场'
  const parts = [label, scope]
  if (form.recipe === 'range_refetch' && form.date_start) {
    parts.push(`${form.date_start} ~ ${form.date_end || form.date_start}`)
  }
  if (stockIngestSupportsYears(form.recipe) && form.years) parts.push(`近 ${form.years} 年`)
  return parts.join(' · ')
}

/** 旧任务编辑时映射到统一模型；历史记录本身不改写。 */
export function stockIngestFormFromTask(
  taskType: string,
  params: Record<string, any> | null | undefined,
): StockIngestFormValue | null {
  const raw = params || {}
  let recipe: StockIngestRecipe | null = null
  if (taskType === 'stock_ingest') recipe = raw.recipe as StockIngestRecipe
  else if (taskType === 'update' || taskType === 'ingest_codes') recipe = 'daily_update'
  else if (taskType === 'backfill') recipe = 'history_backfill'
  else if (taskType === 'ingest_date') recipe = 'range_refetch'
  if (!recipe || !STOCK_INGEST_RECIPE_LABEL[recipe]) return null
  const codes = Array.isArray(raw.codes) ? raw.codes.map(String) : []
  return createStockIngestForm({
    recipe,
    scope: codes.length ? 'selected' : 'all',
    codes,
    date_start: raw.date_start || raw.date || '',
    date_end: raw.date_end || raw.date_start || raw.date || '',
    years: raw.years ?? null,
    concurrency: raw.concurrency ?? null,
  })
}
