import { computed, ref, watch, type Ref } from 'vue'

export interface StockAnalysisSelectable {
  code: string
  name: string | null
}

export interface StockAnalysisSelectionOptions {
  maxItems?: number
  onLimitReached?: (limit: number) => void
}

/** 股票行情工作台共享的当前观察与跨页对比队列状态机。 */
export function useStockAnalysisSelection<T extends StockAnalysisSelectable>(
  sourceItems: Readonly<Ref<readonly T[]>>,
  options: StockAnalysisSelectionOptions = {},
) {
  const limit = options.maxItems ?? 6
  const lookup = ref<Record<string, T>>({})
  const activeCode = ref('')
  const pinnedCodes = ref<string[]>([])

  const activeItem = computed(() => lookup.value[activeCode.value] ?? null)
  const items = computed(() => {
    if (!activeCode.value) return []
    return Array.from(new Set([activeCode.value, ...pinnedCodes.value]))
      .slice(0, limit)
      .map((code) => lookup.value[code])
      .filter((item): item is T => Boolean(item))
  })

  watch(sourceItems, (nextItems) => {
    const retainedPinned = Object.fromEntries(pinnedCodes.value
      .map((code) => [code, lookup.value[code]] as const)
      .filter((entry): entry is readonly [string, T] => Boolean(entry[1])))
    // 跨页只保留固定对比项和当前页，避免遍历大量分页后 lookup 无界增长。
    lookup.value = {
      ...retainedPinned,
      ...Object.fromEntries(nextItems.map((item) => [item.code, item])),
    }
    if (!nextItems.length) {
      activeCode.value = ''
      return
    }
    if (!nextItems.some((item) => item.code === activeCode.value)) {
      activeCode.value = nextItems[0]!.code
    }
  }, { immediate: true })

  function remember(item: T): void {
    lookup.value = { ...lookup.value, [item.code]: item }
  }

  function isPinned(code: string): boolean {
    return pinnedCodes.value.includes(code)
  }

  function togglePinned(item: T): boolean {
    remember(item)
    if (isPinned(item.code)) {
      pinnedCodes.value = pinnedCodes.value.filter((code) => code !== item.code)
      return true
    }
    const occupied = new Set([activeCode.value, ...pinnedCodes.value].filter(Boolean))
    if (!occupied.has(item.code) && occupied.size >= limit) {
      options.onLimitReached?.(limit)
      return false
    }
    pinnedCodes.value = [...pinnedCodes.value, item.code]
    return true
  }

  function select(item: T): void {
    remember(item)
    activeCode.value = item.code
  }

  function activate(code: string): void {
    if (lookup.value[code]) activeCode.value = code
  }

  function remove(code: string): void {
    pinnedCodes.value = pinnedCodes.value.filter((item) => item !== code)
    if (code !== activeCode.value) return
    activeCode.value = pinnedCodes.value[0] || sourceItems.value[0]?.code || ''
  }

  function clear(): void {
    pinnedCodes.value = []
    activeCode.value = sourceItems.value[0]?.code || ''
  }

  return {
    activeCode,
    activeItem,
    items,
    pinnedCodes,
    isPinned,
    togglePinned,
    select,
    activate,
    remove,
    clear,
  }
}
