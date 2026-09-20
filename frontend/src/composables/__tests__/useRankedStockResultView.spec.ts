import { describe, expect, it } from 'vitest'
import { nextTick, ref } from 'vue'
import type { ScoreRunRow } from '@/api/scoreProfile'
import { useRankedStockResultView } from '../useRankedStockResultView'

const rows: ScoreRunRow[] = [
  { rank: 2, code: '000002.SZ', name: 'A', board: '主板', total_score: 90, grade: '观察', sub_scores: {}, is_st: false, score_status: 'ranked' },
  { rank: 1, code: '000001.SZ', name: 'B', board: '主板', total_score: 95, grade: '主升浪核心', sub_scores: {}, is_st: false, score_status: 'ranked' },
]

describe('useRankedStockResultView', () => {
  it('统一消费隐藏列与默认排序，列头排序只覆盖当前会话', async () => {
    const defaults = ref<Record<string, unknown>>({
      defaultSort: 'name',
      hiddenColumns: ['board'],
    })
    const view = useRankedStockResultView({
      rows: () => rows,
      columnKeys: ['rank', 'code', 'name', 'board', 'score'],
      componentValueOf: (_slotId, field) => defaults.value[field],
    })

    expect(view.columns.value.map((column) => column.key)).toEqual(['rank', 'code', 'name', 'score'])
    expect(view.rows.value.map((row) => row.name)).toEqual(['A', 'B'])

    view.onSortChange({ prop: 'code', order: 'ascending' })
    expect(view.rows.value.map((row) => row.code)).toEqual(['000001.SZ', '000002.SZ'])

    defaults.value = { defaultSort: 'score', hiddenColumns: [] }
    await nextTick()
    expect(view.columns.value.map((column) => column.key)).toContain('board')
    expect(view.rows.value.map((row) => row.rank)).toEqual([1, 2])
  })
})
