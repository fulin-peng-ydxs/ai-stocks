import { computed, ref, watch } from 'vue'

export type TableSortOrder = 'asc' | 'desc'
type ElementSortOrder = 'ascending' | 'descending' | null

export interface TableSortChange {
  prop: string
  order: ElementSortOrder
}

export interface UseTableSortOptions<Field extends string = string> {
  slotId: string
  defaultSort: `${Field}:${TableSortOrder}` | Field
  componentValueOf: (slotId: string, field: string) => unknown
  allowedFields?: readonly Field[]
  defaultOrder?: TableSortOrder
  onChanged?: () => void
}

function normalizeOrder(value: string | undefined, fallback: TableSortOrder): TableSortOrder {
  return value === 'asc' || value === 'desc' ? value : fallback
}

function splitSort(value: unknown, fallback: string, fallbackOrder: TableSortOrder): [string, TableSortOrder] {
  const raw = String(value || fallback)
  const [field, order] = raw.split(':')
  const fallbackField = fallback.split(':')[0]
  return [field || fallbackField, normalizeOrder(order, fallbackOrder)]
}

function elementOrder(order: TableSortOrder): Exclude<ElementSortOrder, null> {
  return order === 'desc' ? 'descending' : 'ascending'
}

// 排序单向默认机制（DESIGN「设置抽屉」）：组件配置层 defaultSort 只提供默认值，列头点击排序
// 只写会话覆盖（sessionSort），不回写配置层——页面临时排序不污染长期默认；抽屉改默认时清掉会话覆盖、页面跟随。
export function useTableSort<Field extends string = string>(options: UseTableSortOptions<Field>) {
  const fallbackOrder = options.defaultOrder ?? 'desc'
  const allowed = computed(() => new Set<string>(options.allowedFields ?? []))
  const configuredSort = computed(() => {
    const raw = options.componentValueOf(options.slotId, 'defaultSort')
    const [rawField, rawOrder] = splitSort(raw, options.defaultSort, fallbackOrder)
    const fallbackField = String(options.defaultSort).split(':')[0]
    const field = allowed.value.size === 0 || allowed.value.has(rawField) ? rawField : fallbackField
    return { field: field as Field, order: rawOrder }
  })

  // 会话覆盖：null=跟随配置层默认；列头排序只写这里，不写回 defaultSort。
  const sessionSort = ref<{ field: Field; order: TableSortOrder } | null>(null)
  // 抽屉改默认排序 → 清掉会话覆盖，页面跟随新默认（单向：默认→会话）。
  watch(configuredSort, () => { sessionSort.value = null })

  const sortBy = computed(() => sessionSort.value?.field ?? configuredSort.value.field)
  const sortOrder = computed(() => sessionSort.value?.order ?? configuredSort.value.order)
  const elementDefaultSort = computed(() => ({
    prop: sortBy.value,
    order: elementOrder(sortOrder.value),
  }))

  function setSort(field: Field, order: TableSortOrder): void {
    sessionSort.value = { field, order }
    options.onChanged?.()
  }

  function onSortChange({ prop, order }: TableSortChange): void {
    if (!prop || !order) {
      const [field, fallback] = splitSort(options.defaultSort, options.defaultSort, fallbackOrder)
      setSort(field as Field, fallback)
      return
    }
    if (allowed.value.size > 0 && !allowed.value.has(prop)) return
    setSort(prop as Field, order === 'descending' ? 'desc' : 'asc')
  }

  return { sortBy, sortOrder, elementDefaultSort, setSort, onSortChange }
}
