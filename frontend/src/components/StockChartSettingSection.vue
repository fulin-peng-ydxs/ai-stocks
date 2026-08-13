<script setup lang="ts">
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import type {
  AuxiliaryChartSlot,
  AuxiliaryChartType,
} from '@/composables/useStockChartPreferences'

defineProps<{
  slot2: AuxiliaryChartType
  slot3: AuxiliaryChartType
  testIdPrefix?: string
}>()

const emit = defineEmits<{
  change: [slot: AuxiliaryChartSlot, value: string | number | boolean]
}>()

const auxiliaryChartOptions = [
  { label: '成交量', value: 'volume' },
  { label: 'MACD', value: 'macd' },
  { label: '隐藏', value: 'hidden' },
]
</script>

<template>
  <PageSettingSection title="图表设置" desc="图表类型、显隐和拖动后的高度会自动保存。">
    <slot name="before" />
    <div class="setting-item">
      <div class="setting-label">图表一</div>
      <div class="fixed-chart-value" :data-testid="`${testIdPrefix || 'chart'}-slot1-kline`">K线（固定，不可隐藏）</div>
    </div>
    <div class="setting-item">
      <div class="setting-label">图表二</div>
      <PageSegmented
        :model-value="slot2"
        :options="auxiliaryChartOptions"
        aria-label="图表二类型"
        :test-id="`${testIdPrefix || 'chart'}-slot2`"
        @update:model-value="emit('change', 'slot2', $event)"
      />
    </div>
    <div class="setting-item">
      <div class="setting-label">图表三</div>
      <PageSegmented
        :model-value="slot3"
        :options="auxiliaryChartOptions"
        aria-label="图表三类型"
        :test-id="`${testIdPrefix || 'chart'}-slot3`"
        @update:model-value="emit('change', 'slot3', $event)"
      />
    </div>
  </PageSettingSection>
</template>

<style scoped>
.setting-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.setting-label {
  color: var(--page-settings-text-subtle);
  font-size: var(--app-font-size-body);
}
.fixed-chart-value {
  min-height: 38px;
  display: flex;
  align-items: center;
  padding: 0 10px;
  border: 1px solid var(--page-settings-seg-active-border);
  border-radius: 10px;
  background: var(--page-settings-seg-active-bg);
  color: var(--page-settings-text);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
}
</style>
