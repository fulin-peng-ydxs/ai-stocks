// 个股详情「当前集合」导航 store —— 列表→详情→上一个/下一个 共享同一批股票。
// 集合来源：选中的分组（group）/ 列表的临时勾选或当前页（list）。localStorage 持久化，刷新不丢。
import { defineStore } from 'pinia'

export interface SetItem {
  code: string
  name?: string | null
}

interface State {
  source: '' | 'group' | 'list'
  label: string          // 展示名，如分组名 / “查询结果”
  groupId: string        // source=group 时
  items: SetItem[]       // 有序成员
}

const KEY = 'ai-stocks:stockSet'

function load(): State {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) return JSON.parse(raw) as State
  } catch {
    /* ignore */
  }
  return { source: '', label: '', groupId: '', items: [] }
}

export const useStockSet = defineStore('stockSet', {
  state: (): State => load(),
  getters: {
    has: (s) => s.items.length > 0,
    codes: (s) => s.items.map((i) => i.code),
    indexOf: (s) => (code: string) => s.items.findIndex((i) => i.code === code),
  },
  actions: {
    _persist() {
      try {
        localStorage.setItem(KEY, JSON.stringify(this.$state))
      } catch {
        /* ignore */
      }
    },
    setSet(source: 'group' | 'list', items: SetItem[], label: string, groupId = '') {
      this.source = source
      this.items = items
      this.label = label
      this.groupId = groupId
      this._persist()
    },
    clear() {
      this.source = ''
      this.label = ''
      this.groupId = ''
      this.items = []
      this._persist()
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
