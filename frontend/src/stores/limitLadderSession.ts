import { defineStore } from 'pinia'
import type { LimitLadderFilters } from '@/api/limitLadder'
import type {
  LimitLadderCardSort,
  LimitLadderCardSortOrder,
} from '@/views/limit-ladder/sorting'
import {
  pageSessionStorageKey,
  readPageSession,
  removePageSession,
  writePageSession,
} from '@/utils/pageSessionStorage'

export interface LimitLadderReturnState {
  tradeDate: string | null
  filters: LimitLadderFilters
  cardSort: LimitLadderCardSort
  cardSortOrder: LimitLadderCardSortOrder
  selectedCode: string
  anchorCode: string
}

interface State {
  returnState: LimitLadderReturnState | null
}

const SESSION_NAMESPACE = 'limit-ladder'
let activeStorageKey = ''

function load(key = pageSessionStorageKey(SESSION_NAMESPACE)): State {
  activeStorageKey = key
  return {
    returnState: readPageSession<State>(SESSION_NAMESPACE)?.returnState ?? null,
  }
}

export const useLimitLadderSessionStore = defineStore('limitLadderSession', {
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
    saveReturnState(state: LimitLadderReturnState) {
      this._ensureIdentity()
      this.returnState = {
        ...state,
        filters: {
          ...state.filters,
          boards: [...state.filters.boards],
        },
      }
      this._persist()
    },
    consumeReturnState(): LimitLadderReturnState | null {
      this._ensureIdentity()
      const snapshot = this.returnState
      this.returnState = null
      this._persist()
      return snapshot
    },
    resetSession() {
      this.returnState = null
      removePageSession(SESSION_NAMESPACE)
      activeStorageKey = pageSessionStorageKey(SESSION_NAMESPACE)
    },
  },
})
