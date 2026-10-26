<script setup lang="ts">
import DataMetricDetails from './DataMetricDetails.vue'
import HelpHint from '@/components/HelpHint.vue'
import { ArrowRight } from '@element-plus/icons-vue'

export type DataMetricInfo =
  | { kind: 'help'; text: string }
  | { kind: 'details'; rows: { label: string; value: string }[]; notes?: string[] }

defineProps<{
  label: string
  value: string
  unit?: string
  summary?: string
  tone?: 'success' | 'warning' | 'danger'
  info: DataMetricInfo
  actionLabel?: string
}>()
defineEmits<{ action: [] }>()
</script>

<template>
  <el-card shadow="never" class="data-metric-card">
    <div class="data-metric-label">
      <span>{{ label }}</span>
      <HelpHint v-if="info.kind === 'help' && info.text.trim()" :text="info.text" :label="`${label}口径说明`" />
      <DataMetricDetails v-else-if="info.kind === 'details' && info.rows.length" :label="label" :rows="info.rows" :notes="info.notes" />
    </div>
    <div class="data-metric-value" :class="tone">
      {{ value }}<span v-if="unit" class="data-metric-unit">{{ unit }}</span>
    </div>
    <div v-if="summary" class="data-metric-summary">{{ summary }}</div>
    <el-button data-button-kind="navigation" v-if="actionLabel" link type="primary" class="data-metric-action" size="small" @click="$emit('action')">
      {{ actionLabel }}<el-icon class="el-icon--right"><ArrowRight /></el-icon>
    </el-button>
  </el-card>
</template>

<style scoped>
.data-metric-card { min-width: 0; }
.data-metric-card :deep(.el-card__body) {
  height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--app-space-1);
  padding: var(--app-space-3) var(--app-space-2);
}
.data-metric-label { display: flex; align-items: center; gap: var(--app-space-1); color: var(--el-text-color-secondary); font-size: var(--app-font-size-table); line-height: var(--app-line-height-table); }
.data-metric-value { color: var(--el-text-color-primary); font-size: var(--app-font-size-data); line-height: var(--app-line-height-data); font-weight: var(--app-font-weight-section); font-variant-numeric: tabular-nums; white-space: nowrap; }
.data-metric-unit { margin-left: var(--app-space-1); font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); font-weight: var(--app-font-weight-regular); }
.success { color: var(--el-color-success); }
.warning { color: var(--app-warning-text); }
.danger { color: var(--app-danger-text); }
.data-metric-summary { width: 100%; min-width: 0; font-size: var(--app-font-size-caption); line-height: var(--app-line-height-caption); color: var(--el-text-color-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.data-metric-action { margin: auto 0 0; }
@container app-viewport (max-height: 700px) {
  .data-metric-card :deep(.el-card__body) { gap: var(--app-space-1); padding: var(--app-space-2) var(--app-space-3); }
  .data-metric-value { font-size: var(--app-font-size-body); line-height: var(--app-line-height-body); }
}
</style>
