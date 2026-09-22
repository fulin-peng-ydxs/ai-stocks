import { computed, ref, watch, type Ref } from 'vue'
import {
  activateCompareCode,
  emptyCompareQueue,
  removeCompareCode,
  toggleComparePin,
  type CompareQueueState,
} from '@/utils/compareQueue'

export interface StockAnalysisSelectable {
  code: string
  name: string | null
}

export interface StockAnalysisSelectionOptions {
  maxItems?: number
  onLimitReached?: (limit: number) => void
  autoSelectFirst?: boolean
}

/** 股票行情工作台共享的当前观察与跨页对比队列状态机。队列顺序稳定,激活只移动高亮不重排。 */
export function useStockAnalysisSelection<T extends StockAnalysisSelectable>(
  sourceItems: Readonly<Ref<readonly T[]>>,
  options: StockAnalysisSelectionOptions = {},
) {
  const limit = options.maxItems ?? 6
  const autoSelectFirst = options.autoSelectFirst ?? true
  const lookup = ref<Record<string, T>>({})
  const queue = ref<CompareQueueState>(emptyCompareQueue())
  const selectionRevision = ref(0)

  const currentState = (): CompareQueueState => queue.value
  function applyState(next: CompareQueueState): void {
    queue.value = {
      queueCodes: [...next.queueCodes],
      pinnedCodes: [...next.pinnedCodes],
      activeCode: next.activeCode,
    }
  }

  const activeCode = computed(() => queue.value.activeCode)
  const activeItem = computed(() => lookup.value[activeCode.value] ?? null)
  const pinnedCodes = computed(() => [...queue.value.pinnedCodes])
  const items = computed(() => {
    if (!activeCode.value) return []
    return queue.value.queueCodes
      .map((code) => lookup.value[code])
      .filter((item): item is T => Boolean(item))
  })

  watch(sourceItems, (nextItems) => {
    // 跨页只保留固定对比项和当前观察，避免遍历大量分页后 lookup 无界增长。
    const retained = Object.fromEntries(
      [...queue.value.pinnedCodes, queue.value.activeCode]
        .map((code) => [code, lookup.value[code]] as const)
        .filter((entry): entry is readonly [string, T] => Boolean(entry[1])),
    )
    lookup.value = {
      ...retained,
      ...Object.fromEntries(nextItems.map((item) => [item.code, item])),
    }
    // 队列剔除已失效项并保持既有插入序；激活项失效则回退到首个源项。
    applyState({
      ...queue.value,
      queueCodes: queue.value.queueCodes.filter((code) => lookup.value[code]),
    })
    if (!nextItems.length) {
      applyState({ ...queue.value, activeCode: '' })
      return
    }
    if (!activeCode.value && !autoSelectFirst) {
      return
    }
    if (!nextItems.some((item) => item.code === activeCode.value)) {
      applyState(activateCompareCode(currentState(), nextItems[0]!.code, limit))
    } else if (activeCode.value && !queue.value.queueCodes.includes(activeCode.value)) {
      applyState({
        ...queue.value,
        queueCodes: [activeCode.value, ...queue.value.queueCodes],
      })
    }
  }, { immediate: true })

  function remember(item: T): void {
    lookup.value = { ...lookup.value, [item.code]: item }
  }

  function isPinned(code: string): boolean {
    return queue.value.pinnedCodes.includes(code)
  }

  function togglePinned(item: T): boolean {
    remember(item)
    const result = toggleComparePin(currentState(), item.code, limit)
    if (result.limitReached) {
      options.onLimitReached?.(limit)
      return false
    }
    applyState(result.state)
    return true
  }

  function select(item: T): void {
    if (item.code === activeCode.value) return
    remember(item)
    applyState(activateCompareCode(currentState(), item.code, limit))
    selectionRevision.value += 1
  }

  function activate(code: string): void {
    if (code === activeCode.value) return
    if (lookup.value[code]) {
      applyState(activateCompareCode(currentState(), code, limit))
      selectionRevision.value += 1
    }
  }

  function remove(code: string): void {
    const previousActiveCode = activeCode.value
    applyState(removeCompareCode(currentState(), code, sourceItems.value[0]?.code || ''))
    if (activeCode.value !== previousActiveCode) selectionRevision.value += 1
  }

  function clear(): void {
    const active = autoSelectFirst ? sourceItems.value[0]?.code || '' : ''
    applyState({ queueCodes: active ? [active] : [], pinnedCodes: [], activeCode: active })
  }

  return {
    activeCode,
    activeItem,
    items,
    selectionRevision,
    pinnedCodes,
    isPinned,
    togglePinned,
    select,
    activate,
    remove,
    clear,
  }
}
