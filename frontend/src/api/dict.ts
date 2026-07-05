// 数据字典 API（stage5·T7）：对应 backend/api/dicts.py。
import http from './client'

export interface DictType {
  id: string
  code: string
  name: string
  enabled: boolean
  sort: number
  remark?: string | null
  item_count?: number
  created_at?: string | null
  updated_at?: string | null
}

export interface DictItem {
  id: string
  type_code: string
  code: string
  label: string
  enabled: boolean
  sort: number
  remark?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface DictPage<T> {
  list: T[]
  total: number
  page: number
  size: number
}

export interface DictTypeQuery {
  q?: string
  enabled?: boolean | null
  page?: number
  size?: number
}

export interface DictItemQuery {
  type_code: string
  q?: string
  enabled?: boolean | null
  page?: number
  size?: number
}

export interface DictTypeWrite {
  code?: string
  name: string
  enabled?: boolean
  sort?: number
  remark?: string | null
}

export interface DictItemWrite {
  type_code?: string
  code?: string
  label: string
  enabled?: boolean
  sort?: number
  remark?: string | null
}

export interface PublicDictItems {
  type_code: string
  items: DictItem[]
  fallback: boolean
  version: string
}

export function listDictTypes(query: DictTypeQuery = {}): Promise<DictPage<DictType>> {
  return http.get('/dict/types', { params: query })
}

export function createDictType(body: DictTypeWrite & { code: string }): Promise<DictType> {
  return http.post('/dict/types', body)
}

export function updateDictType(code: string, body: DictTypeWrite): Promise<DictType> {
  return http.put(`/dict/types/${encodeURIComponent(code)}`, body)
}

export function deleteDictType(code: string): Promise<void> {
  return http.delete(`/dict/types/${encodeURIComponent(code)}`)
}

export function listDictItems(query: DictItemQuery): Promise<DictPage<DictItem>> {
  return http.get('/dict/items', { params: query })
}

export function getPublicDictItems(typeCode: string): Promise<PublicDictItems> {
  return http.get('/dict/items/public', { params: { type_code: typeCode } })
}

export function createDictItem(body: DictItemWrite & { type_code: string; code: string }): Promise<DictItem> {
  return http.post('/dict/items', body)
}

export function updateDictItem(typeCode: string, code: string, body: DictItemWrite): Promise<DictItem> {
  return http.put(`/dict/items/${encodeURIComponent(typeCode)}/${encodeURIComponent(code)}`, body)
}

export function deleteDictItem(typeCode: string, code: string): Promise<void> {
  return http.delete(`/dict/items/${encodeURIComponent(typeCode)}/${encodeURIComponent(code)}`)
}
