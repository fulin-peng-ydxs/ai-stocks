import type { LocationQuery, LocationQueryRaw } from 'vue-router'
import type { BoardType, SectorSortField } from '@/api/sectors'
import { normalizeMarketBenchmarkCode } from '@/utils/marketBenchmarks'

export interface SectorSourceQuery {
  type?: BoardType
  sort?: SectorSortField
  order?: 'asc' | 'desc'
  keyword?: string
  page?: string
  scope?: 'watchlist'
  date?: string
  return_to?: string
}

export interface SectorListPreferences {
  defaultType?: BoardType | '' | string
  defaultScope?: 'all' | 'watchlist' | string
  defaultChartMode?: 'compare' | 'kline' | string
  benchmarkCode?: string
}

export interface ResolvedSectorListState {
  query: SectorSourceQuery
  boardType: BoardType | ''
  listScope: 'all' | 'watchlist'
  chartMode: 'compare' | 'kline'
  benchmarkCode: string
  keyword: string
  page: number
}

const SORT_FIELDS: readonly SectorSortField[] = [
  'pct_today', 'pct_5d', 'pct_10d', 'pct_20d',
  'net_inflow', 'net_inflow_3d', 'net_inflow_5d', 'net_inflow_10d', 'net_inflow_20d',
  'up_count',
]
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const TRUSTED_SECTOR_RETURN_RE = /^\/(?:limit-ladder|board|screen)(?:\?|$)|^\/stocks(?:\/[^/?#]+)?(?:\?|$)/

/** 板块详情只接受已知业务列表作为返回来源，避免形成开放重定向。 */
export function trustedSectorReturnPath(value: unknown): string | undefined {
  if (typeof value !== 'string' || value.length > 2000) return undefined
  return TRUSTED_SECTOR_RETURN_RE.test(value) ? value : undefined
}

/** 所有“走势板块”入口共用同一详情地址结构，禁止消费组件各自拼 return_to。 */
export function sectorDetailLocation(boardCode: string, returnPath?: string) {
  const trustedReturnPath = trustedSectorReturnPath(returnPath)
  return {
    path: `/sectors/${encodeURIComponent(boardCode)}`,
    query: trustedReturnPath ? { return_to: trustedReturnPath } : undefined,
  }
}

/** 详情页返回按钮按可信来源展示明确文案，未识别来源统一回到板块行情。 */
export function sectorReturnLabel(raw: LocationQuery): string {
  const returnPath = trustedSectorReturnPath(raw.return_to)
  if (returnPath?.startsWith('/limit-ladder')) return '返回连板天梯'
  if (returnPath?.startsWith('/stocks/')) return '返回个股详情'
  if (returnPath?.startsWith('/stocks')) return '返回个股查询'
  if (returnPath?.startsWith('/board')) return '返回每日榜单'
  if (returnPath?.startsWith('/screen')) return '返回策略筛选'
  return '返回板块行情'
}

/** 详情页与列表页共用来源参数白名单，非法字段逐项丢弃。 */
export function sanitizeSectorSourceQuery(raw: LocationQuery): SectorSourceQuery {
  const result: SectorSourceQuery = {}
  const get = (key: string): string => {
    const value = raw[key]
    return typeof value === 'string' ? value : ''
  }

  const type = get('type')
  if (type === 'concept' || type === 'industry') result.type = type
  const sort = get('sort')
  if ((SORT_FIELDS as readonly string[]).includes(sort)) result.sort = sort as SectorSortField
  const order = get('order')
  if (order === 'asc' || order === 'desc') result.order = order
  const keyword = get('keyword').trim().slice(0, 50)
  if (keyword) result.keyword = keyword
  const page = Number(get('page'))
  if (Number.isInteger(page) && page >= 1) result.page = String(page)
  if (get('scope') === 'watchlist') result.scope = 'watchlist'
  const date = get('date')
  if (DATE_RE.test(date)) result.date = date
  const returnTo = trustedSectorReturnPath(get('return_to'))
  if (returnTo) result.return_to = returnTo
  return result
}

export function toLocationQuery(query: SectorSourceQuery): LocationQueryRaw {
  return { ...query }
}

/** URL 来源态优先于已保存偏好；非法偏好按页面默认值回落。 */
export function resolveSectorListState(
  raw: LocationQuery,
  preferences: SectorListPreferences,
  canViewWatchlist: boolean,
): ResolvedSectorListState {
  const query = sanitizeSectorSourceQuery(raw)
  const savedType = preferences.defaultType === 'concept' || preferences.defaultType === 'industry'
    ? preferences.defaultType
    : ''
  const requestedScope = query.scope ?? (
    preferences.defaultScope === 'watchlist' ? 'watchlist' : 'all'
  )
  const benchmarkCode = normalizeMarketBenchmarkCode(preferences.benchmarkCode ?? '')
  return {
    query,
    boardType: query.type ?? savedType,
    listScope: canViewWatchlist && requestedScope === 'watchlist' ? 'watchlist' : 'all',
    chartMode: preferences.defaultChartMode === 'kline' ? 'kline' : 'compare',
    benchmarkCode,
    keyword: query.keyword ?? '',
    page: query.page ? Number(query.page) : 1,
  }
}

/** 详情页显式返回列表时统一清洗来源参数，禁止透传任意 query。 */
export function sectorListLocation(raw: LocationQuery): {
  path: '/sectors'
  query: LocationQueryRaw
} | string {
  const query = sanitizeSectorSourceQuery(raw)
  if (query.return_to) return query.return_to
  return { path: '/sectors', query: toLocationQuery(query) }
}
