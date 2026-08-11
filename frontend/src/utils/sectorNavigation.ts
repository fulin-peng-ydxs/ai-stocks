import type { LocationQuery, LocationQueryRaw } from 'vue-router'
import type { BoardType, SectorSortField } from '@/api/sectors'

export interface SectorSourceQuery {
  type?: BoardType
  sort?: SectorSortField
  order?: 'asc' | 'desc'
  keyword?: string
  page?: string
  scope?: 'watchlist'
  date?: string
}

const SORT_FIELDS: readonly SectorSortField[] = ['pct_today', 'pct_5d', 'net_inflow']
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

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
  return result
}

export function toLocationQuery(query: SectorSourceQuery): LocationQueryRaw {
  return { ...query }
}
