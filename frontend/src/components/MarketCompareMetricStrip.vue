<script setup lang="ts">
import { computed } from 'vue'
import HelpHint from '@/components/HelpHint.vue'

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

function metricDescription(item: MarketMetricStripItem): string {
  const value = item.parts?.map((part) => part.text).join(' ') || item.value
  return `${item.label}：${value}`
}
</script>

<template>
  <div
    class="market-metric-strip"
    :aria-label="ariaLabel"
    :data-testid="`${testIdPrefix}-strip`"
    :style="stripStyle"
  >
    <div v-for="item in items" :key="item.key" class="market-metric-cell">
      <el-button
        text
        class="market-metric app-interaction-target"
        :class="{
          'market-metric--active': item.key === activeKey,
          'is-selected': item.key === activeKey,
        }"
        :aria-pressed="item.key === activeKey"
        :aria-label="metricDescription(item)"
        :data-testid="`${testIdPrefix}-${item.key}`"
        @click="emit('select', item.key)"
      >
        <span class="market-metric-content app-interaction-content">
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
      <span class="market-metric-help">
        <HelpHint :text="metricDescription(item)" />
      </span>
    </div>
  </div>
</template>

<style scoped>
.market-metric-strip {
  display: grid;
  flex: 0 0 auto;
  overflow-x: auto;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--app-surface-container);
}
.market-metric-cell {
  position: relative;
  min-width: 0;
}
.market-metric-help { display: none; }
.market-metric.el-button.is-text {
  box-sizing: border-box;
  min-width: 0;
  width: 100%;
  height: 100%;
  min-height: 58px;
  margin: 0;
  padding: var(--app-space-2) var(--app-space-3);
  justify-content: flex-start;
  border: 0;
  border-right: 1px solid var(--el-border-color-lighter);
  background: transparent;
  box-shadow: none;
  border-radius: 0;
  color: var(--el-text-color-primary);
  text-align: left;
}
.market-metric-cell:last-child .market-metric.el-button {
  border-right: 0;
}
.market-metric.el-button > :deep(span) {
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
  max-width: 100%;
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.market-metric strong {
  display: block;
  max-width: 100%;
  overflow: hidden;
  margin-top: 2px;
  font-size: var(--app-font-size-data);
  font-weight: var(--app-font-weight-section);
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
/* 连续指标属于一个分段栏：定位线留在单元格内部，不叠加独立卡片框和投影。 */
.market-metric::before { content: none; }
.market-metric.el-button.is-selected {
  background: var(--app-interaction-selected-background);
}
.market-metric.is-selected::after {
  content: '';
  position: absolute;
  inset: auto 0 0;
  height: var(--app-nav-indicator-size);
  background: var(--el-color-primary);
  pointer-events: none;
}
@media (hover: hover) and (pointer: fine) {
  .market-metric.el-button:not(:disabled):hover {
    background: var(--chrome-bg-soft-hover);
  }
  .market-metric.el-button.is-selected:not(:disabled):hover {
    background: var(--app-interaction-selected-background);
  }
}
@container app-viewport (max-width: 1180px) {
  .market-metric-strip {
    grid-template-columns: repeat(3, minmax(84px, 1fr)) !important;
  }
}
@container app-viewport (max-height: 700px) {
  /* 低高度收起辅助数值时，提供独立且可见的说明入口，避免整块重复提示。 */
  .market-metric-strip {
    grid-template-columns: none !important;
    grid-auto-flow: column;
    grid-auto-columns: minmax(max-content, 1fr);
  }
  .market-metric.el-button.is-text {
    min-height: var(--app-control-height-md);
    padding: var(--app-space-1) var(--app-control-height-md) var(--app-space-1) var(--app-space-2);
  }
  .market-metric-help {
    display: inline-flex;
    position: absolute;
    right: var(--app-space-2);
    top: 50%;
    transform: translateY(-50%);
  }
  .market-metric-label {
    font-size: var(--app-font-size-caption);
    line-height: var(--app-line-height-caption);
  }
  .market-metric strong { display: none !important; }
}
</style>
