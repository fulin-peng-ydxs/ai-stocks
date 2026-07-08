<script setup lang="ts">
import AppPagination from '@/components/AppPagination.vue'
import type { Sort } from 'element-plus'

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

withDefaults(defineProps<{
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
  pagination?: PaginationConfig
}>(), {
  kind: 'data-table',
  loading: false,
  height: '100%',
  size: 'default',
  clickable: false,
  stripe: false,
  border: true,
  framed: false,
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
    :class="[
      `app-data-table--${kind}`,
      {
        'app-data-table--clickable': clickable,
        'app-data-table--framed': framed,
        'app-data-table--with-pager': Boolean(pagination),
      },
    ]"
  >
    <el-table
      v-bind="$attrs"
      :data="data"
      :height="height"
      :size="size"
      :row-key="rowKey"
      :default-sort="defaultSort"
      :row-class-name="rowClassName"
      :stripe="stripe"
      :border="border"
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

    <div v-if="pagination" class="app-data-table__pager">
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
  height: 100%;
  flex: 1 1 auto;
  flex-direction: column;
}

.app-data-table--framed {
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color-overlay);
}

.app-data-table__table {
  flex: 1 1 auto;
  min-height: 0;
}

.app-data-table :deep(th .cell) {
  display: inline-flex;
  align-items: center;
  white-space: nowrap;
}

.app-data-table :deep(th .caret-wrapper) {
  flex: 0 0 auto;
}

.app-data-table--wide-table :deep(.el-table__body-wrapper) {
  overflow-x: auto;
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
