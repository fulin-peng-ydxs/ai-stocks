<script setup lang="ts">
import StockChartLegend from './StockChartLegend.vue'
import type { StockChartLegendItem } from './StockChartLegend.vue'

withDefaults(defineProps<{
  title: string
  items?: readonly StockChartLegendItem[]
  legendLabel?: string
  divided?: boolean
}>(), {
  items: () => [],
  legendLabel: undefined,
  divided: false,
})
</script>

<template>
  <header class="stock-chart-panel__header" :class="{ 'is-divided': divided }">
    <strong class="stock-chart-panel__title">{{ title }}</strong>
    <StockChartLegend v-if="items.length" :items="items" :aria-label="legendLabel" />
    <slot />
    <slot name="tail" />
  </header>
</template>

<style scoped>
.stock-chart-panel__header {
  min-height: 32px;
  padding: 5px var(--app-space-3);
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-lighter);
  font-variant-numeric: tabular-nums;
}

.stock-chart-panel__header.is-divided {
  border-top: 1px solid var(--el-border-color-lighter);
}

.stock-chart-panel__title {
  flex: 0 0 auto;
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
}

@media (max-width: 1180px) {
  .stock-chart-panel__header {
    gap: var(--app-space-2);
  }
}
</style>
