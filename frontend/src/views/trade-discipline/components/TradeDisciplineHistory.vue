<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppControlItem from '@/components/AppControlItem.vue'
import AppControlRow from '@/components/AppControlRow.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import type { AppRowAction } from '@/components/rowActions'
import type { TableSortChange } from '@/composables/useTableSort'
import {
  listTradeDisciplineCheckins,
  type CheckinHistoryQuery,
  type CheckinHistoryRow,
  type StockOption,
  type TradeDisciplineRule,
} from '@/api/tradeDiscipline'
import StockOptionSelect from './StockOptionSelect.vue'

const props = withDefaults(defineProps<{
  query: CheckinHistoryQuery
  page: number
  pageSize: number
  rules: TradeDisciplineRule[]
  border: boolean
  sortBy?: 'trade_date'
  sortOrder?: 'asc' | 'desc'
  defaultSort?: { prop: string; order: 'ascending' | 'descending' }
  hiddenColumns?: string[]
}>(), {
  sortBy: 'trade_date',
  sortOrder: 'desc',
  defaultSort: () => ({ prop: 'trade_date', order: 'descending' }),
  hiddenColumns: () => [],
})
const emit = defineEmits<{
  'update:query': [value: CheckinHistoryQuery]
  'page-change': [value: number]
  'size-change': [value: number]
  'sort-change': [value: TableSortChange]
  detail: [row: CheckinHistoryRow]
}>()

const rows = ref<CheckinHistoryRow[]>([])
const total = ref(0)
const loading = ref(false)
const loadError = ref(false)
const selectedStock = ref<StockOption | null>(null)
const reasonText = ref(props.query.reason || '')
let loadSeq = 0

const ruleOptions = computed(() => props.rules.map((rule) => ({
  value: rule.id,
  label: rule.name || rule.proposed_name || '未命名规则',
})))
const assessmentOptions = [
  { value: 'complied', label: '已履约' },
  { value: 'breached', label: '未履约' },
]
const operationOptions = [
  { value: 'false', label: '有操作' },
  { value: 'true', label: '无操作' },
]
const amendedOptions = [
  { value: 'true', label: '已修正' },
  { value: 'false', label: '未修正' },
]
const noOperationValue = computed(() => props.query.no_operation === undefined
  ? '' : String(props.query.no_operation))
const amendedValue = computed(() => props.query.amended === undefined
  ? '' : String(props.query.amended))
const hasFilters = computed(() => Object.entries(props.query).some(([, value]) => (
  value !== undefined && value !== null && value !== ''
)))
const querySignature = computed(() => JSON.stringify([
  props.page,
  props.query.date_from,
  props.query.date_to,
  props.query.rule_id,
  props.query.assessment,
  props.query.no_operation,
  props.query.amended,
  props.query.stock,
  props.query.reason,
  props.sortBy,
  props.sortOrder,
]))

function updateQuery(patch: Partial<CheckinHistoryQuery>): void {
  emit('update:query', { ...props.query, ...patch })
  if (props.page !== 1) emit('page-change', 1)
}

function booleanValue(value: string[] | string): boolean | undefined {
  const scalar = Array.isArray(value) ? value[0] : value
  return scalar === '' ? undefined : scalar === 'true'
}

function selectStock(value: StockOption | null): void {
  selectedStock.value = value
  updateQuery({ stock: value?.code || undefined })
}

function resetFilters(): void {
  selectedStock.value = null
  reasonText.value = ''
  emit('update:query', {})
  if (props.page !== 1) emit('page-change', 1)
}

function openDetail(row: CheckinHistoryRow): void {
  emit('detail', row)
}

function rowActions(row: CheckinHistoryRow): AppRowAction[] {
  return [{
    key: 'detail', label: '详情', testId: `history-detail-${row.id}`,
    onClick: (event) => { event?.stopPropagation(); openDetail(row) },
  }]
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  return value.replace('T', ' ').replace(/\.\d+/, '').replace(/\+.*$/, '').slice(0, 16)
}

function colVisible(key: string): boolean {
  return !props.hiddenColumns.includes(key)
}

async function load(): Promise<void> {
  const seq = ++loadSeq
  loading.value = true
  loadError.value = false
  try {
    const result = await listTradeDisciplineCheckins({
      ...props.query,
      sort_by: props.sortBy,
      sort_order: props.sortOrder,
      page: props.page,
      page_size: props.pageSize,
    })
    if (seq !== loadSeq) return
    rows.value = result.list
    total.value = result.total
  } catch {
    if (seq !== loadSeq) return
    rows.value = []
    total.value = 0
    loadError.value = true
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

watch(() => props.query.stock, (stock) => {
  if (!stock) selectedStock.value = null
  else if (selectedStock.value?.code !== stock) {
    selectedStock.value = { code: stock, name: stock, board: null, industry: null }
  }
}, { immediate: true })
watch(() => props.query.reason, (reason) => { reasonText.value = reason || '' })
watch(querySignature, load, { immediate: true })
defineExpose({ reload: load })
</script>

<template>
  <div class="history-workspace">
    <el-card shadow="never" class="filter-card history-filter-card">
      <AppControlRow class="filter-row" aria-label="履约历史筛选">
        <AppControlItem class="date-filter">
          <div class="date-range" aria-label="交易日期范围">
            <TradeDatePicker :model-value="query.date_from || null" clearable placement="bottom-start" :fallback-placements="['bottom-start']" placeholder="开始交易日" @update:model-value="updateQuery({ date_from: $event || undefined })" />
            <span>至</span>
            <TradeDatePicker :model-value="query.date_to || null" clearable placement="bottom-start" :fallback-placements="['bottom-start']" placeholder="结束交易日" @update:model-value="updateQuery({ date_to: $event || undefined })" />
          </div>
        </AppControlItem>
        <AppFilterSelect class="rule-filter" data-testid="history-rule-filter" :model-value="query.rule_id || ''" :options="ruleOptions" :multiple="false" placeholder="全部规则" @change="updateQuery({ rule_id: String($event) || undefined })" />
        <AppFilterSelect class="assessment-filter" data-testid="history-assessment-filter" :model-value="query.assessment || ''" :options="assessmentOptions" :multiple="false" placeholder="全部结果" @change="updateQuery({ assessment: (String($event) || undefined) as CheckinHistoryQuery['assessment'] })" />
        <AppFilterSelect class="operation-filter" data-testid="history-operation-filter" :model-value="noOperationValue" :options="operationOptions" :multiple="false" placeholder="全部操作状态" @change="updateQuery({ no_operation: booleanValue($event) })" />
        <AppFilterSelect class="amended-filter" data-testid="history-amended-filter" :model-value="amendedValue" :options="amendedOptions" :multiple="false" placeholder="全部修订状态" @change="updateQuery({ amended: booleanValue($event) })" />
        <StockOptionSelect class="stock-filter" :model-value="selectedStock" clearable @update:model-value="selectStock" />
        <AppSearchInput class="reason-filter" v-model="reasonText" placeholder="违规原因" @search="updateQuery({ reason: reasonText.trim() || undefined })" />
        <el-button :disabled="!hasFilters" @click="resetFilters">重置</el-button>
      </AppControlRow>
    </el-card>

    <AppStateBlock
      v-if="loadError"
      state="error"
      title="履约历史加载失败"
      description="当前筛选结果不可用，请重试"
      retry
      @retry="load"
    />
    <AppDataTable
      v-else
      :data="rows"
      :loading="loading"
      row-key="id"
      kind="wide-table"
      aria-label="履约历史"
      empty-text="暂无符合条件的履约记录"
      :border="border"
      :default-sort="defaultSort"
      stripe
      framed
      clickable
      :pagination="{ currentPage: page, pageSize, total }"
      @row-click="openDetail"
      @page-change="emit('page-change', $event)"
      @size-change="emit('size-change', $event)"
      @sort-change="emit('sort-change', $event)"
    >
      <AppTableColumn v-if="colVisible('trade_date')" prop="trade_date" label="交易日" role="date" sortable="custom" :sort-orders="['descending', 'ascending']" />
      <AppTableColumn v-if="colVisible('rule_name')" label="规则" role="name"><template #default="{ row }">{{ row.rule_name }} · v{{ row.version_no }}</template></AppTableColumn>
      <AppTableColumn v-if="colVisible('assessment')" prop="assessment" label="用户自评">
        <template #default="{ row }"><el-tag :type="row.assessment === 'complied' ? 'success' : 'danger'" effect="plain">{{ row.assessment === 'complied' ? '已履约' : '未履约' }}</el-tag></template>
      </AppTableColumn>
      <AppTableColumn v-if="colVisible('operation_count')" label="操作"><template #default="{ row }">{{ row.no_operation ? '无操作' : `${row.operation_count} 笔` }}</template></AppTableColumn>
      <AppTableColumn v-if="colVisible('reason_name_snapshot')" prop="reason_name_snapshot" label="违规摘要" role="description"><template #default="{ row }">{{ row.reason_name_snapshot || '—' }}</template></AppTableColumn>
      <AppTableColumn v-if="colVisible('current_revision_no')" label="修订">
        <template #default="{ row }"><el-tag :type="row.status === 'amended' ? 'warning' : 'info'" effect="plain">r{{ row.current_revision_no }}{{ row.status === 'amended' ? ' · 已修正' : '' }}</el-tag></template>
      </AppTableColumn>
      <AppTableColumn v-if="colVisible('updated_at')" prop="updated_at" label="最后更新"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></AppTableColumn>
      <AppTableColumn label="操作" role="action-compact" fixed="right">
        <template #default="{ row }"><AppRowActions :actions="rowActions(row)" :inline-limit="1" /></template>
      </AppTableColumn>
      <template #empty>
        <div class="app-table-empty">
          <span class="app-table-empty__description">暂无符合条件的履约记录</span>
          <el-button v-if="hasFilters" @click="resetFilters">重置筛选</el-button>
        </div>
      </template>
    </AppDataTable>
  </div>
</template>

<style scoped>
.history-workspace { width: 100%; height: 100%; min-height: 0; min-width: 0; flex: 1 1 auto; display: flex; flex-direction: column; gap: var(--app-space-3); }
.history-filter-card { flex: none; }
.filter-row { flex-wrap: wrap; }
.date-filter { width: 300px; max-width: 100%; }
.rule-filter { width: 180px; }
.assessment-filter { width: 120px; }
.operation-filter,
.amended-filter { width: 150px; }
.stock-filter { width: 200px; }
.reason-filter { width: 180px; }
.date-range { display: grid; grid-template-columns: minmax(110px, 1fr) auto minmax(110px, 1fr); align-items: center; gap: var(--app-space-2); }
.date-range :deep(.el-date-editor) { width: 100%; }
</style>
