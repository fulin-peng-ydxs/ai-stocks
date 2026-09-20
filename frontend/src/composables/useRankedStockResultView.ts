import { computed, ref, toValue, watch, type MaybeRefOrGetter } from 'vue'
import type { ScoreRunRow } from '@/api/scoreProfile'
import {
  rankedStockColumns,
  type RankedStockColumnKey,
} from '@/components/ranked-stock/types'

export type RankedStockResultSort = 'score' | 'code' | 'name'

interface RankedStockResultViewOptions {
  rows: MaybeRefOrGetter<ScoreRunRow[]>
  columnKeys: MaybeRefOrGetter<RankedStockColumnKey[]>
  componentValueOf: (slotId: string, field: string) => unknown
  slotId?: string
}

/**
 * 排名结果表的组件配置投影：统一列显隐、默认排序与列头排序的会话覆盖。
 * 配置层只提供默认值；列头交互只改当前会话，不反写页面或用户配置。
 */
export function useRankedStockResultView(options: RankedStockResultViewOptions) {
  const slotId = options.slotId ?? 'result'
  const configuredSort = computed<RankedStockResultSort>(() => {
    const raw = options.componentValueOf(slotId, 'defaultSort')
    return raw === 'code' || raw === 'name' ? raw : 'score'
  })
  const sessionSort = ref<RankedStockResultSort | null>(null)
  watch(configuredSort, () => { sessionSort.value = null })
  const sort = computed(() => sessionSort.value ?? configuredSort.value)
  const hiddenColumns = computed<string[]>(() => {
    const value = options.componentValueOf(slotId, 'hiddenColumns')
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
  })
  const columnVisible = (key: string): boolean => !hiddenColumns.value.includes(key)

  const rows = computed(() => {
    const list = [...toValue(options.rows)]
    if (sort.value === 'code') list.sort((a, b) => a.code.localeCompare(b.code))
    else if (sort.value === 'name') list.sort((a, b) => (a.name || '').localeCompare(b.name || ''))
    else list.sort((a, b) => (a.rank ?? Number.MAX_SAFE_INTEGER) - (b.rank ?? Number.MAX_SAFE_INTEGER))
    return list
  })
  const columns = computed(() => rankedStockColumns(
    toValue(options.columnKeys).filter((key) => key === 'rank' || columnVisible(key)),
  ))

  const sortProps: Record<string, RankedStockResultSort> = {
    total_score: 'score',
    rank: 'score',
    code: 'code',
    name: 'name',
  }
  function onSortChange({ prop }: { prop: string; order: string | null }): void {
    sessionSort.value = sortProps[prop] ?? 'score'
  }

  return { rows, columns, columnVisible, onSortChange }
}
