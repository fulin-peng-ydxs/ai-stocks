import { computed, type Ref } from 'vue'

export interface StockBatchItem {
  code: string
  name: string | null
}

/** 跨分页保留批量选择，并统一当前页全选、半选与单行切换行为。 */
export function useStockBatchSelection<TRow extends StockBatchItem>(
  rows: Ref<TRow[]>,
  selected: Ref<StockBatchItem[]>,
) {
  const selectedCodes = computed(() => selected.value.map((item) => item.code))
  const selectedSet = computed(() => new Set(selectedCodes.value))
  const isSelected = (code: string) => selectedSet.value.has(code)

  function toggle(row: StockBatchItem): void {
    const index = selected.value.findIndex((item) => item.code === row.code)
    if (index >= 0) selected.value.splice(index, 1)
    else selected.value.push({ code: row.code, name: row.name })
  }

  const allCurrentSelected = computed(() => (
    rows.value.length > 0 && rows.value.every((row) => isSelected(row.code))
  ))
  const someCurrentSelected = computed(() => (
    rows.value.some((row) => isSelected(row.code)) && !allCurrentSelected.value
  ))

  function toggleAllCurrent(checked: boolean): void {
    if (checked) {
      for (const row of rows.value) {
        if (!isSelected(row.code)) selected.value.push({ code: row.code, name: row.name })
      }
      return
    }
    const currentCodes = new Set(rows.value.map((row) => row.code))
    selected.value = selected.value.filter((item) => !currentCodes.has(item.code))
  }

  return {
    selectedCodes,
    isSelected,
    toggle,
    allCurrentSelected,
    someCurrentSelected,
    toggleAllCurrent,
  }
}
