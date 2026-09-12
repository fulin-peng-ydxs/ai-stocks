// 个股详情「当前集合」导航 store —— 列表→详情→上一个/下一个 共享同一批股票。
// 集合来源：选中的分组（group）/ 列表的临时勾选或当前页（list）。
// 只保留在当前浏览器 Tab 会话，刷新不丢，关闭 Tab、退出登录或切换身份后清理。
import { defineStore } from 'pinia'
import { readAuth } from '@/api/authToken'
import type { StockListParams } from '@/api/stocks'
import type { GroupMembersParams } from '@/api/stockGroup'
import {
  clearAllPageSessions,
  pageSessionStorageKey,
  readPageSession,
  removePageSession,
  writePageSession,
} from '@/utils/pageSessionStorage'

export interface SetItem {
  code: string
  name?: string | null
}

export type SetQuery =
  | { kind: 'stocks'; params: StockListParams }
  | { kind: 'group'; groupId: string; params: GroupMembersParams }

export interface StockListState {
  mode: 'list' | 'group'
  q: string
  board: string
  membershipBoardCode?: string
  excludeSt: boolean
  tradeDate: string
  sortBy: string
  sortOrder: 'asc' | 'desc'
  page: number
  size: number
  activeGid: string
  groupPage: number
  groupSize: number
  groupQ: string
  groupSortBy: string
  groupSortOrder: 'asc' | 'desc'
}

interface State {
  source: '' | 'group' | 'list'
  label: string          // 展示名，如分组名 / “查询结果”
  returnPath: string     // 详情页返回当前集合来源页
  groupId: string        // source=group 时
  items: SetItem[]       // 有序成员
  query: SetQuery | null
  total: number
  loadedPages: number[]
  pageSize: number
  listState: StockListState | null
}

const SESSION_NAMESPACE = 'stock-set'
const LEGACY_SESSION_PREFIX = 'ai-stocks:stockSet:v2'
const LEGACY_LOCAL_STORAGE_KEY = 'ai-stocks:stockSet'
let activeStorageKey = ''

function emptyState(): State {
  return {
    source: '', label: '', returnPath: '', groupId: '', items: [], query: null,
    total: 0, loadedPages: [], pageSize: 20, listState: null,
  }
}

export function stockSetSessionStorageKey(): string {
  return pageSessionStorageKey(SESSION_NAMESPACE)
}

function legacySessionStorageKey(): string {
  const auth = readAuth()
  return `${LEGACY_SESSION_PREFIX}:${auth.tenant?.id || 'anonymous'}:${auth.user?.id || 'anonymous'}`
}

function clearLegacyLocalState(): void {
  try {
    localStorage.removeItem(LEGACY_LOCAL_STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

function load(key = stockSetSessionStorageKey()): State {
  activeStorageKey = key
  clearLegacyLocalState()
  try {
    const parsed = readPageSession<Partial<State>>(SESSION_NAMESPACE, [legacySessionStorageKey()])
    if (parsed) {
      const query = parsed.query && !('kind' in parsed.query)
        ? { kind: 'stocks' as const, params: parsed.query as unknown as StockListParams }
        : parsed.query ?? null
      return {
        source: parsed.source ?? '',
        label: parsed.label ?? '',
        returnPath: parsed.returnPath ?? '',
        groupId: parsed.groupId ?? '',
        items: parsed.items ?? [],
        query,
        total: parsed.total ?? parsed.items?.length ?? 0,
        loadedPages: parsed.loadedPages ?? [],
        pageSize: parsed.pageSize ?? Math.min(Math.max(parsed.items?.length ?? 20, 1), 100),
        listState: parsed.listState ?? null,
      }
    }
  } catch {
    /* ignore */
  }
  return emptyState()
}

export const useStockSet = defineStore('stockSet', {
  state: (): State => load(),
  getters: {
    has: (s) => s.items.length > 0,
    codes: (s) => s.items.map((i) => i.code),
    indexOf: (s) => (code: string) => s.items.findIndex((i) => i.code === code),
  },
  actions: {
    _ensureIdentity() {
      const key = stockSetSessionStorageKey()
      if (key === activeStorageKey) return
      Object.assign(this, load(key))
    },
    _persist() {
      this._ensureIdentity()
      writePageSession(SESSION_NAMESPACE, this.$state)
    },
    setSet(
      source: 'group' | 'list',
      items: SetItem[],
      label: string,
      groupId = '',
      meta?: {
        query?: SetQuery | null
        total?: number
        loadedPages?: number[]
        pageSize?: number
        returnPath?: string
      },
    ) {
      this._ensureIdentity()
      this.source = source
      this.items = items
      this.label = label
      this.returnPath = meta?.returnPath ?? '/stocks?restore=1'
      this.groupId = groupId
      this.query = meta?.query ?? null
      this.total = meta?.total ?? items.length
      this.loadedPages = meta?.loadedPages ?? []
      this.pageSize = meta?.pageSize ?? Math.min(Math.max(items.length, 1), 100)
      this._persist()
    },
    setListState(state: StockListState) {
      this._ensureIdentity()
      this.listState = state
      this._persist()
    },
    clearListState() {
      this._ensureIdentity()
      this.listState = null
      this._persist()
    },
    consumeListState(): StockListState | null {
      this._ensureIdentity()
      const snapshot = this.listState
      if (!snapshot) return null
      this.listState = null
      this._persist()
      return snapshot
    },
    appendPage(items: SetItem[], page: number) {
      this._ensureIdentity()
      const seen = new Set(this.items.map((i) => i.code))
      const incoming = items.filter((it) => !seen.has(it.code))
      const minPage = this.loadedPages.length ? Math.min(...this.loadedPages) : page
      if (page < minPage) {
        this.items.unshift(...incoming)
      } else {
        this.items.push(...incoming)
      }
      if (!this.loadedPages.includes(page)) this.loadedPages.push(page)
      this._persist()
    },
    mergeItemsNear(items: SetItem[], anchorCode: string) {
      this._ensureIdentity()
      const seen = new Set(this.items.map((i) => i.code))
      const incoming = items.filter((it) => !seen.has(it.code))
      if (!incoming.length) return
      const anchorIndex = this.items.findIndex((i) => i.code === anchorCode)
      const insertAt = anchorIndex >= 0 ? anchorIndex + 1 : this.items.length
      this.items.splice(insertAt, 0, ...incoming)
      this._persist()
    },
    setTotal(total: number) {
      this._ensureIdentity()
      this.total = total
      this._persist()
    },
    clearGroupContext() {
      this._ensureIdentity()
      const hasGroupContext = this.source === 'group' || this.groupId || this.query?.kind === 'group'
      if (!hasGroupContext) return false
      this.source = ''
      this.label = ''
      this.returnPath = ''
      this.groupId = ''
      this.items = []
      this.query = null
      this.total = 0
      this.loadedPages = []
      this.pageSize = 20
      this._persist()
      return true
    },
    clear() {
      this._ensureIdentity()
      Object.assign(this, emptyState())
      this._persist()
    },
    resetSession(clearAllIdentities = false) {
      Object.assign(this, emptyState())
      try {
        if (clearAllIdentities) {
          clearAllPageSessions([`${LEGACY_SESSION_PREFIX}:`])
        } else {
          removePageSession(SESSION_NAMESPACE, [legacySessionStorageKey()])
        }
      } catch {
        /* ignore */
      }
      clearLegacyLocalState()
      activeStorageKey = stockSetSessionStorageKey()
    },
    // 返回相对 code 的前/后一个 code（无则 null）
    neighbor(code: string, dir: -1 | 1): string | null {
      const i = this.items.findIndex((x) => x.code === code)
      if (i < 0) return null
      const j = i + dir
      return j >= 0 && j < this.items.length ? this.items[j].code : null
    },
  },
})
