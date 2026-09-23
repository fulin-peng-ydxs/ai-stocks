<script setup lang="ts">
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppPagination from '@/components/AppPagination.vue'
import { syncTableCellVisualOverflow } from '@/components/table/cellVisualOverflow'
import type { Sort } from 'element-plus'
import { computed, nextTick, onBeforeUnmount, onMounted, onUpdated, ref, watch } from 'vue'

defineOptions({ inheritAttrs: false })

type TableKind = 'data-table' | 'wide-table'
type RowKey = string | ((row: any) => string)
type RowClassName = string | ((data: { row: any; rowIndex: number }) => string)

interface PaginationConfig {
  currentPage: number
  pageSize: number
  total: number
  pageSizes?: number[]
  small?: boolean
}

const props = withDefaults(defineProps<{
  data: unknown[]
  kind?: TableKind
  loading?: boolean
  height?: string | number
  size?: '' | 'large' | 'default' | 'small'
  rowKey?: RowKey
  defaultSort?: Record<string, unknown>
  rowClassName?: RowClassName
  tableClass?: string
  clickable?: boolean
  stripe?: boolean
  border?: boolean
  framed?: boolean
  emptyText?: string
  loadingText?: string
  ariaLabel?: string
  pagination?: PaginationConfig
  /** 宽表默认常显滚动条；普通表格可按需显式开启。 */
  scrollbarAlwaysOn?: boolean | null
  /** 仅用于抽屉、展开行、局部详情等非主成长表；页面主列表不得开启。 */
  embedded?: boolean
}>(), {
  kind: 'data-table',
  loading: false,
  size: 'default',
  clickable: false,
  stripe: false,
  border: false,
  framed: false,
  loadingText: '正在加载数据…',
  scrollbarAlwaysOn: null,
  embedded: false,
})

const resolvedHeight = computed(() => props.height ?? (!props.embedded ? '100%' : undefined))
const initialLoading = computed(() => props.loading && props.data.length === 0)
const initialLoadingStyle = computed(() => {
  if (props.height == null) return undefined
  return { height: typeof props.height === 'number' ? `${props.height}px` : props.height }
})
const resolvedScrollbarAlwaysOn = computed(
  () => props.scrollbarAlwaysOn ?? props.kind === 'wide-table',
)
const tableRef = ref<{ $el?: HTMLElement } | null>(null)
let tableResizeObserver: ResizeObserver | null = null
let observedTableRoot: HTMLElement | null = null
let overflowSyncPending = false

function observeTableResize(root: HTMLElement): void {
  if (typeof ResizeObserver === 'undefined' || observedTableRoot === root) return
  tableResizeObserver?.disconnect()
  tableResizeObserver = new ResizeObserver(syncCellVisualOverflow)
  tableResizeObserver.observe(root)
  observedTableRoot = root
}

function syncCellVisualOverflow(): void {
  if (overflowSyncPending) return
  overflowSyncPending = true
  void nextTick(() => {
    overflowSyncPending = false
    const root = tableRef.value?.$el
    if (!root) return
    observeTableResize(root)
    syncTableCellVisualOverflow(root)
  })
}

function syncSemanticTableLabels(): void {
  void nextTick(() => {
    const root = tableRef.value?.$el
    if (!root) return
    const header = root.querySelector<HTMLElement>('.el-table__header')
    const body = root.querySelector<HTMLElement>('.el-table__body')
    header?.setAttribute('aria-busy', String(props.loading))
    body?.setAttribute('aria-busy', String(props.loading))
    if (!props.ariaLabel) return
    header?.setAttribute('aria-label', `${props.ariaLabel}表头`)
    body?.setAttribute('aria-label', props.ariaLabel)
  })
}

onMounted(() => {
  syncSemanticTableLabels()
  syncCellVisualOverflow()
})
onUpdated(syncCellVisualOverflow)
onBeforeUnmount(() => {
  tableResizeObserver?.disconnect()
  observedTableRoot = null
  overflowSyncPending = false
})
watch(() => [props.ariaLabel, props.loading, props.data.length], () => {
  syncSemanticTableLabels()
  syncCellVisualOverflow()
})

const emit = defineEmits<{
  'sort-change': [value: Sort]
  'row-click': [row: any, column: any, event: Event]
  'page-change': [value: number]
  'size-change': [value: number]
}>()
</script>

<template>
  <div
    class="app-data-table"
    :aria-busy="loading"
    :class="[
      `app-data-table--${kind}`,
      {
        'app-data-table--fill': !embedded,
        'app-data-table--embedded': embedded,
        'app-data-table--clickable': clickable,
        'app-data-table--framed': framed,
        'app-data-table--with-pager': Boolean(pagination),
      },
    ]"
  >
    <AppStateBlock
      v-if="initialLoading"
      state="loading"
      :size="embedded ? 'compact' : 'default'"
      :title="loadingText"
      :style="initialLoadingStyle"
      data-testid="app-data-table-initial-loading"
    />
    <el-table
      v-else
      ref="tableRef"
      v-bind="$attrs"
      :data="data"
      :fit="true"
      :aria-label="ariaLabel"
      :aria-busy="loading"
      :height="resolvedHeight"
      :size="size"
      :row-key="rowKey"
      :default-sort="defaultSort"
      :row-class-name="rowClassName"
      :stripe="stripe"
      :border="border"
      :scrollbar-always-on="resolvedScrollbarAlwaysOn"
      v-loading="loading"
      :class="['app-data-table__table', tableClass, { clickable }]"
      @sort-change="(value: Sort) => emit('sort-change', value)"
      @row-click="(row: any, column: any, event: Event) => emit('row-click', row, column, event)"
    >
      <slot />
      <template v-if="$slots.empty || emptyText" #empty>
        <slot name="empty">
          <span>{{ emptyText }}</span>
        </slot>
      </template>
    </el-table>

    <div v-if="pagination && !initialLoading" class="app-data-table__pager">
      <AppPagination
        :current-page="pagination.currentPage"
        :page-size="pagination.pageSize"
        :total="pagination.total"
        :page-sizes="pagination.pageSizes"
        :small="pagination.small"
        @current-change="(value: number) => emit('page-change', value)"
        @size-change="(value: number) => emit('size-change', value)"
      />
    </div>
  </div>
</template>

<style scoped>
.app-data-table {
  display: flex;
  min-height: 0;
  min-width: 0;
  width: 100%;
  flex-direction: column;
}

.app-data-table--fill {
  height: 100%;
  flex: 1 1 auto;
}

.app-data-table--embedded {
  height: auto;
  flex: 0 0 auto;
}

.app-data-table--framed {
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color-overlay);
}

.app-data-table__table {
  min-height: 0;
  width: 100%;
}

.app-data-table--fill .app-data-table__table {
  flex: 1 1 auto;
}

.app-data-table :deep(th .cell) {
  display: inline-flex;
  align-items: center;
  white-space: nowrap;
}

.app-data-table :deep(.el-table__body .cell.app-table-cell--visual-overflow) {
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-data-table :deep(td.app-table-column--single-line .cell) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-data-table :deep(td.app-table-column--tabular .cell) {
  font-variant-numeric: tabular-nums;
}

.app-data-table :deep(th .caret-wrapper) {
  flex: 0 0 auto;
}

.app-data-table--clickable :deep(.el-table__row) {
  cursor: pointer;
}

.app-data-table__pager {
  flex: 0 0 auto;
  display: flex;
  justify-content: flex-end;
  padding: 10px 12px 0;
}

.app-data-table--framed .app-data-table__pager {
  padding: 10px 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}
</style>
