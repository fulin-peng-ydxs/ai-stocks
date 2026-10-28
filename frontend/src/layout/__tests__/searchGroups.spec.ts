import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { SEARCH_GROUPS } from '../searchGroups'
import { getPageEntry } from '../pageRegistry'

const sources: Record<keyof typeof SEARCH_GROUPS, [string, string?]> = {
  board: ['BoardView.vue'],
  stocks: ['StocksView.vue'], users: ['system/UserManageView.vue'],
  audit: ['system/AuditLogView.vue'], quality: ['data/QualityView.vue'],
  indicators: ['ConfigView.vue'], assets: ['data/OverviewView.vue'],
  ladder: ['limit-ladder/LimitLadderFilters.vue', 'LimitLadderView.vue'],
  history: ['trade-discipline/components/TradeLedgerWorkspace.vue', 'TradeDisciplineView.vue'],
}
const source = (file: string) => readFileSync(new URL(`../../views/${file}`, import.meta.url), 'utf8')

describe('高级搜索页面接入契约', () => {
  for (const [key, group] of Object.entries(SEARCH_GROUPS)) {
    it(`${group.label}的候选、字段插槽、配置槽及真实组件配置读取保持一致`, () => {
      const [file, host = file] = sources[key as keyof typeof SEARCH_GROUPS]
      const text = source(file)
      expect(text).toContain(`group="${key}"`)
      for (const field of group.fields) expect(text).toContain(`#${field.key}>`)
      expect(source(host)).toMatch(/<LayoutHost\b[^>]*:component-value-of="componentValueOf"/)
      expect(group.defaults).toHaveLength(2)
      expect(new Set(group.defaults).size).toBe(2)
      expect(group.defaults.every(key => group.fields.some(field => field.key === key))).toBe(true)
      const entry = getPageEntry(group.pageKey)!
      const slot = entry.layout.slots.find(slot => slot.id === group.slotId)!
      expect(slot.component).toBe('filter-bar')
      expect(slot.config?.commonFields).toEqual(group.defaults)
      expect(entry.componentMeta?.[slot.id]?.searchFields).toEqual(group.fields)
    })
  }

  it('个股最小权限设置白名单保留搜索配置', () => {
    expect(source('StocksView.vue')).toContain("canViewGroups.value ? undefined : ['filter', 'table', 'chart']")
  })
})
