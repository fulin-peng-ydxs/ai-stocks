<script setup lang="ts">
import { computed } from 'vue'
import HelpHint from '@/components/HelpHint.vue'
import { splitHeadingText } from '@/utils/headingText'
import StockChartLegend from './StockChartLegend.vue'
import { useControlRowSizing } from '../controlRowSizing'
import type { StockChartLegendItem } from './StockChartLegend.vue'

const props = withDefaults(defineProps<{
  title: string
  items?: readonly StockChartLegendItem[]
  legendLabel?: string
}>(), {
  items: () => [],
  legendLabel: undefined,
})
const row = useControlRowSizing()
// 动态面板标题保留原始复权/参数信息，但说明不再混入可见标题名称。
const heading = computed(() => splitHeadingText(props.title))
</script>

<template>
  <header class="stock-chart-panel__header app-control-row-scope" :style="row.style.value" :data-control-row="row.size.value">
    <strong class="stock-chart-panel__title">{{ heading.label }}</strong>
    <HelpHint v-if="heading.description" :text="heading.description" :label="`${heading.label}口径说明`" />
    <StockChartLegend v-if="items.length" :items="items" :aria-label="legendLabel" />
    <slot />
    <slot name="tail" />
  </header>
</template>

<style scoped>
.stock-chart-panel__header {
  min-height: var(--app-control-row-height);
  padding: var(--app-space-1) var(--app-space-3);
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-lighter);
  font-variant-numeric: tabular-nums;
}

.stock-chart-panel__title {
  flex: 0 0 auto;
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
}

@container app-viewport (max-width: 1180px) {
  .stock-chart-panel__header {
    gap: var(--app-space-2);
  }
}
</style>
