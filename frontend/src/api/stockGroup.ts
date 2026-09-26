// 股票分组 API（个股查询·篮子，对应 backend/api/stock_groups.py）
import http from './client'
import type { StockRelatedBoards } from '@/types/relatedBoards'

export interface GroupSummary {
  id: string
  name: string
  group_date: string | null
  description: string
  color: string
  is_default: boolean
  member_count: number
  updated_at: string
}

export interface GroupMember {
  code: string
  name: string | null
  add_date: string | null
  ret: number | null        // 最近涨幅（加入日 → 最新，小数）
  price: number | null      // 最新收盘价（元）
  pct_chg: number | null    // 最新交易日当日涨跌幅（%）
  last_date: string | null
  is_st?: boolean | null
  st_as_of_date?: string | null
  note: string
  related_boards?: StockRelatedBoards | null
}

export interface GroupDetail {
  id: string
  name: string
  group_date: string | null
  description: string
  color: string
  is_default: boolean
  members: {
    total: number
    page: number
    size: number
    list: GroupMember[]
  }
  avg_ret: number | null    // 整组等权平均涨幅（小数）
  count: number
  created_at: string
  updated_at: string
}

export function listGroups(): Promise<GroupSummary[]> {
  return http.get('/stock-groups')
}
export interface GroupMembersParams {
  page?: number
  size?: number
  q?: string
  boards?: string
  /** 兼容旧调用；新页面使用 boards 传本页原有板块值。 */
  board?: string
  membership_board_code?: string
  exclude_st?: boolean
  exclude_delisted?: boolean
  trade_date?: string
  sort_by?: string
  sort_order?: string
}

export function getGroup(gid: string, params?: GroupMembersParams): Promise<GroupDetail> {
  return http.get(`/stock-groups/${gid}`, { params })
}
export function createGroup(body: {
  name: string
  group_date?: string
  description?: string
  color?: string
  codes?: string[]
}): Promise<{ id: string }> {
  return http.post('/stock-groups', body)
}
export function updateGroup(gid: string, body: {
  name?: string
  group_date?: string
  description?: string
  color?: string
}): Promise<{ id: string }> {
  return http.patch(`/stock-groups/${gid}`, body)
}
export function deleteGroup(gid: string): Promise<{ msg: string }> {
  return http.delete(`/stock-groups/${gid}`)
}
export function addMembers(gid: string, codes: string[], addDate?: string): Promise<{ added: number }> {
  return http.post(`/stock-groups/${gid}/members`, { codes, add_date: addDate })
}
export function removeMembers(gid: string, codes: string[]): Promise<{ msg: string }> {
  return http.delete(`/stock-groups/${gid}/members`, { data: { codes } })
}
export function setMemberDate(gid: string, code: string, addDate: string): Promise<unknown> {
  return http.patch(`/stock-groups/${gid}/members/${code}`, { add_date: addDate })
}
