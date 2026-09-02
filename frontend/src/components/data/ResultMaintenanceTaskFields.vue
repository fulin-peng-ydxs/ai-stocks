<script setup lang="ts">
import { computed } from 'vue'
import AppDatePicker from '@/components/AppDatePicker.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import StockCodeMultiSelect from '@/components/data/StockCodeMultiSelect.vue'
import {
  RESULT_MAINTENANCE_DESCRIPTION,
  type ResultMaintenanceTaskForm,
  type ResultMaintenanceTaskType,
  type ResultTargetMode,
} from '@/utils/resultMaintenanceTask'

const props = withDefaults(defineProps<{
  modelValue: ResultMaintenanceTaskForm
  taskType: ResultMaintenanceTaskType
  testIdPrefix?: string
}>(), { testIdPrefix: 'result-maintenance' })
const emit = defineEmits<{ 'update:modelValue': [value: ResultMaintenanceTaskForm] }>()

const targetOptions = computed<{ label: string; value: ResultTargetMode }[]>(() => {
  const base: { label: string; value: ResultTargetMode }[] = [
    { label: '最新完整交易日', value: 'latest' },
    { label: '固定交易日', value: 'fixed' },
  ]
  return props.taskType === 'recompute'
    ? [...base, { label: '全部快照', value: 'all' }]
    : base
})

function patch(value: Partial<ResultMaintenanceTaskForm>) {
  emit('update:modelValue', { ...props.modelValue, ...value })
}
</script>

<template>
  <el-form-item label="目标范围">
    <PageSegmented
      :model-value="modelValue.target_mode"
      :options="targetOptions"
      :test-id="`${testIdPrefix}-target-mode`"
      tone="primary"
      aria-label="结果维护目标范围"
      @update:model-value="patch({ target_mode: $event as ResultTargetMode })"
    />
  </el-form-item>
  <el-form-item v-if="modelValue.target_mode === 'fixed'" label="固定日期">
    <AppDatePicker
      :model-value="modelValue.trade_date"
      type="date"
      value-format="YYYY-MM-DD"
      format="YYYY-MM-DD"
      placeholder="选择交易日"
      :clearable="false"
      :data-testid="`${testIdPrefix}-trade-date`"
      style="width: 100%"
      @update:model-value="patch({ trade_date: String($event || '') })"
    />
    <span v-if="taskType === 'limit_ladder_invalidate'" class="hint">固定日期表示从该日开始向后失效。</span>
  </el-form-item>
  <template v-if="taskType === 'stock_board_correlation'">
    <el-form-item label="股票范围">
      <PageSegmented
        :model-value="modelValue.stock_scope"
        :options="[{ label: '全市场', value: 'all' }, { label: '指定股票', value: 'selected' }]"
        :test-id="`${testIdPrefix}-stock-scope`"
        tone="primary"
        aria-label="走势相关重算股票范围"
        @update:model-value="patch({ stock_scope: $event as 'all' | 'selected' })"
      />
    </el-form-item>
    <el-form-item v-if="modelValue.stock_scope === 'selected'" label="指定股票">
      <StockCodeMultiSelect
        :model-value="modelValue.codes"
        :test-id="`${testIdPrefix}-codes`"
        aria-label="走势相关重算指定股票"
        @update:model-value="patch({ codes: $event })"
      />
    </el-form-item>
  </template>
  <el-alert
    type="info"
    :closable="false"
    :title="RESULT_MAINTENANCE_DESCRIPTION[taskType]"
  />
</template>

<style scoped>
.hint {
  display: block;
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}
</style>
