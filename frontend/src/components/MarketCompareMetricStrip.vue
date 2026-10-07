<script setup lang="ts">
import { computed } from 'vue'

export type MarketMetricTone = 'up' | 'down' | 'muted' | 'neutral'

export interface MarketMetricStripItem {
  key: string
  label: string
  value: string
  tone?: MarketMetricTone
  parts?: { text: string; tone?: MarketMetricTone }[]
}

const props = defineProps<{
  items: MarketMetricStripItem[]
  activeKey: string
  ariaLabel: string
  testIdPrefix: string
}>()

const emit = defineEmits<{
  select: [key: string]
}>()

const stripStyle = computed(() => ({
  gridTemplateColumns: `repeat(${Math.max(1, props.items.length)}, minmax(72px, 1fr))`,
}))
</script>

<template>
  <div
    class="market-metric-strip"
    :aria-label="ariaLabel"
    :data-testid="`${testIdPrefix}-strip`"
    :style="stripStyle"
  >
    <el-button
      v-for="(item, index) in items"
      :key="item.key"
      text
      class="market-metric"
      :class="{
        'market-metric--active': item.key === activeKey,
        'market-metric--lead': index === 0,
      }"
      :aria-pressed="item.key === activeKey"
      :title="`${item.label}：${item.parts?.map((part) => part.text).join(' ') || item.value}`"
      :data-testid="`${testIdPrefix}-${item.key}`"
      @click="emit('select', item.key)"
    >
      <span class="market-metric-content">
        <span class="market-metric-label">{{ item.label }}</span>
        <strong v-if="item.parts?.length" class="market-metric-value">
          <span
            v-for="(part, partIndex) in item.parts"
            :key="`${part.text}-${partIndex}`"
            :class="part.tone"
          >{{ part.text }}</span>
        </strong>
        <strong v-else :class="item.tone">{{ item.value }}</strong>
      </span>
    </el-button>
  </div>
</template>

<style scoped>
.market-metric-strip {
  display: grid;
  flex: 0 0 auto;
  overflow-x: auto;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: color-mix(in srgb, var(--app-section-bg) 54%, var(--el-bg-color));
}
.market-metric {
  box-sizing: border-box;
  min-width: 0;
  width: 100%;
  height: auto;
  min-height: 58px;
  margin: 0;
  padding: var(--app-space-2) var(--app-space-3);
  justify-content: flex-start;
  border-right: 1px solid var(--el-border-color-lighter);
  border-radius: 0;
  color: var(--el-text-color-primary);
  text-align: left;
}
.market-metric.el-button + .market-metric.el-button {
  margin-left: 0;
}
.market-metric:last-child {
  border-right: 0;
}
.market-metric:hover,
.market-metric--active {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 70%, transparent);
}
.market-metric--active {
  box-shadow: inset 0 -2px 0 var(--el-color-primary);
}
.market-metric:focus-visible {
  outline: 2px solid var(--el-color-primary-light-5);
  outline-offset: -2px;
}
.market-metric :deep(.el-button__text) {
  min-width: 0;
  width: 100%;
}
.market-metric-content {
  display: flex;
  min-width: 0;
  width: 100%;
  align-items: flex-start;
  flex-direction: column;
}
.market-metric-label {
  display: block;
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.market-metric strong {
  display: block;
  overflow: hidden;
  margin-top: 2px;
  font-size: var(--app-font-size-data);
  line-height: var(--app-line-height-data);
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.market-metric-value {
  display: flex !important;
  align-items: baseline;
}
.market-metric-value span + span {
  margin-left: 2px;
}
.market-metric .up {
  color: var(--market-up-color);
}
.market-metric .down {
  color: var(--market-down-color);
}
.market-metric .muted {
  color: var(--el-text-color-placeholder);
}
.market-metric--lead {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 58%, transparent);
}
.market-metric--lead.market-metric--active {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 70%, transparent);
}
@container app-viewport (max-width: 1180px) {
  .market-metric-strip {
    grid-template-columns: repeat(3, minmax(84px, 1fr)) !important;
  }
}
@container app-viewport (max-height: 700px) {
  /* 低高度仍保留唯一指标切换入口，只把辅助数值收敛到悬浮说明。 */
  .market-metric-strip {
    grid-template-columns: none !important;
    grid-auto-flow: column;
    grid-auto-columns: minmax(90px, 1fr);
  }
  .market-metric {
    min-height: var(--app-control-height-md);
    padding: var(--app-space-1) var(--app-space-2);
  }
  .market-metric-label {
    font-size: var(--app-font-size-caption);
    line-height: var(--app-line-height-caption);
  }
  .market-metric strong { display: none !important; }
}
</style>
