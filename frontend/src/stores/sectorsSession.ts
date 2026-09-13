import { defineStore } from 'pinia'
import type {
  BoardType,
  SectorMemberSortField,
  SectorRow,
  SectorSortField,
} from '@/api/sectors'
import type { CompareMetric } from '@/utils/sectorCompare'
import {
  pageSessionStorageKey,
  readPageSession,
  removePageSession,
  writePageSession,
} from '@/utils/pageSessionStorage'

export interface SectorListReturnState {
  tradeDate: string | null
  boardType: BoardType | ''
  listScope: 'all' | 'watchlist'
  keyword: string
  sortBy: SectorSortField
  sortOrder: 'asc' | 'desc'
  page: number
  size: number
  chartMode: 'compare' | 'kline'
  benchmarkCode: string
  compareMetric: CompareMetric
  compareWindow: number
  rangeDays: number
  analysisPanelVisible: boolean
  activeCode: string
  pinnedCodes: string[]
  queueCodes: string[]
  queueRows: SectorRow[]
}

export interface SectorDetailReturnState {
  boardCode: string
  tradeDate: string | null
  memberKeyword: string
  memberPage: number
  memberSize: number
  memberSortBy: SectorMemberSortField
  memberSortOrder: 'asc' | 'desc'
  viewDays: number
  returnPath: string
}

interface State {
  listReturnState: SectorListReturnState | null
  detailReturnState: SectorDetailReturnState | null
}

const SESSION_NAMESPACE = 'sectors'
let activeStorageKey = ''

function emptyState(): State {
  return { listReturnState: null, detailReturnState: null }
}

function load(key = pageSessionStorageKey(SESSION_NAMESPACE)): State {
  activeStorageKey = key
  const persisted = readPageSession<Partial<State>>(SESSION_NAMESPACE)
  return {
    listReturnState: persisted?.listReturnState ?? null,
    detailReturnState: persisted?.detailReturnState ?? null,
  }
}

export const useSectorsSessionStore = defineStore('sectorsSession', {
  state: (): State => load(),
  actions: {
    _ensureIdentity() {
      const key = pageSessionStorageKey(SESSION_NAMESPACE)
      if (key === activeStorageKey) return
      Object.assign(this, load(key))
    },
    _persist() {
      this._ensureIdentity()
      writePageSession<State>(SESSION_NAMESPACE, this.$state)
    },
    saveListReturnState(state: SectorListReturnState) {
      this._ensureIdentity()
      this.listReturnState = {
        ...state,
        pinnedCodes: [...state.pinnedCodes],
        queueCodes: [...state.queueCodes],
        queueRows: state.queueRows.map((row) => ({ ...row })),
      }
      this._persist()
    },
    consumeListReturnState(): SectorListReturnState | null {
      this._ensureIdentity()
      const snapshot = this.listReturnState
      this.listReturnState = null
      this._persist()
      return snapshot
    },
    saveDetailReturnState(state: SectorDetailReturnState) {
      this._ensureIdentity()
      this.detailReturnState = { ...state }
      this._persist()
    },
    consumeDetailReturnState(boardCode: string): SectorDetailReturnState | null {
      this._ensureIdentity()
      const snapshot = this.detailReturnState?.boardCode === boardCode
        ? this.detailReturnState
        : null
      if (snapshot) {
        this.detailReturnState = null
        this._persist()
      }
      return snapshot
    },
    resetSession() {
      Object.assign(this, emptyState())
      removePageSession(SESSION_NAMESPACE)
      activeStorageKey = pageSessionStorageKey(SESSION_NAMESPACE)
    },
  },
})
