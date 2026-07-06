import { computed } from 'vue'

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
  setComponentKnob: (slotId: string, field: string, value: unknown) => void
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

  const sortBy = computed(() => configuredSort.value.field)
  const sortOrder = computed(() => configuredSort.value.order)
  const elementDefaultSort = computed(() => ({
    prop: sortBy.value,
    order: elementOrder(sortOrder.value),
  }))

  function setSort(field: Field, order: TableSortOrder): void {
    options.setComponentKnob(options.slotId, 'defaultSort', `${field}:${order}`)
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
