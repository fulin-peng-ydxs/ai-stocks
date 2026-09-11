<script setup lang="ts">
export interface StockChartLegendItem {
  key: string
  label: string
  value?: string
  color: string
  marker?: 'line' | 'bar'
}

defineProps<{
  items: readonly StockChartLegendItem[]
  ariaLabel?: string
}>()
</script>

<template>
  <div class="stock-chart-legend" :aria-label="ariaLabel">
    <span v-for="item in items" :key="item.key" class="stock-chart-legend__item">
      <i
        class="stock-chart-legend__marker"
        :class="`is-${item.marker ?? 'line'}`"
        :style="{ backgroundColor: item.color }"
        aria-hidden="true"
      />
      <span class="stock-chart-legend__label">{{ item.label }}</span>
      <b v-if="item.value != null" :style="{ color: item.color }">{{ item.value }}</b>
    </span>
  </div>
</template>

<style scoped>
.stock-chart-legend {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
  white-space: nowrap;
}

.stock-chart-legend__item {
  min-width: 0;
  max-width: 128px;
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  overflow: hidden;
}

.stock-chart-legend__marker {
  width: 14px;
  height: 2px;
  flex: 0 0 auto;
  border-radius: 1px;
}

.stock-chart-legend__marker.is-bar {
  width: 5px;
  height: 10px;
}

.stock-chart-legend__label,
.stock-chart-legend__item b {
  overflow: hidden;
  text-overflow: ellipsis;
}

.stock-chart-legend__item b {
  font-weight: var(--app-font-weight-section);
}

@container app-viewport (max-width: 1180px) {
  .stock-chart-legend {
    gap: var(--app-space-2);
  }
}
</style>
