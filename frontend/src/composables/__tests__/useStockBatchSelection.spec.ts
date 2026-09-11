import { ref } from 'vue'
import { describe, expect, it } from 'vitest'
import { useStockBatchSelection, type StockBatchItem } from '@/composables/useStockBatchSelection'

describe('useStockBatchSelection', () => {
  it('跨当前页保留选择，并正确计算全选和半选', () => {
    const rows = ref([
      { code: '000001.SZ', name: '平安银行' },
      { code: '000002.SZ', name: '万科A' },
    ])
    const selected = ref<StockBatchItem[]>([])
    const selection = useStockBatchSelection(rows, selected)

    selection.toggle(rows.value[0]!)
    expect(selection.someCurrentSelected.value).toBe(true)
    selection.toggleAllCurrent(true)
    expect(selection.allCurrentSelected.value).toBe(true)

    rows.value = [{ code: '600000.SH', name: '浦发银行' }]
    selection.toggleAllCurrent(true)
    expect(selection.selectedCodes.value).toEqual(['000001.SZ', '000002.SZ', '600000.SH'])

    selection.toggleAllCurrent(false)
    expect(selection.selectedCodes.value).toEqual(['000001.SZ', '000002.SZ'])
  })
})
