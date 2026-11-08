<script setup lang="ts">
import AppScrollArea from '@/components/AppScrollArea.vue'
import { computed } from 'vue'
import HelpHint from '@/components/HelpHint.vue'
import type { StockQuoteSummaryModel, StockQuoteSummaryWidths } from './stockQuoteSummary'
const props = withDefaults(defineProps<{
  summary: StockQuoteSummaryModel
  widths?: StockQuoteSummaryWidths
  columnGap?: 'standard' | 'relaxed'
}>(), {
  columnGap: 'standard',
})
const columns = computed(() => {
  const rows = Math.max(1, Math.floor(props.summary.rowsPerColumn))
  return Array.from(
    { length: Math.ceil(props.summary.metrics.length / rows) },
    (_, index) => props.summary.metrics.slice(index * rows, (index + 1) * rows),
  )
})
</script>

<template>
  <AppScrollArea as="dl" class="stock-quote-summary" :class="[`stock-quote-summary--gap-${columnGap}`, { 'stock-quote-summary--stable': widths }]">
    <div class="stock-quote-summary__hero">
      <dt v-if="summary.hero.label">{{ summary.hero.label }}</dt>
      <div class="stock-quote-summary__hero-values">
        <dd :style="{ width: widths?.hero.value }" :class="`is-${summary.hero.tone || 'neutral'}`">{{ summary.hero.value }}</dd>
        <div v-if="summary.hero.details?.length" class="stock-quote-summary__hero-details">
          <span
            v-for="(detail, index) in summary.hero.details"
            :key="`${detail.label}-${detail.value}`"
            :class="`is-${detail.tone || 'neutral'}`"
            :style="{ width: widths?.hero.details[index] }"
          >{{ detail.value }}<HelpHint v-if="detail.hint || detail.rawPrecision" :text="detail.hint || detail.rawPrecision || ''" /></span>
        </div>
      </div>
    </div>
    <div v-for="(column, index) in columns" :key="index" class="stock-quote-summary__column">
      <div v-for="metric in column" :key="metric.label" class="stock-quote-summary__metric">
        <dt :style="{ width: widths?.columns[index]?.label }">
          <span>{{ metric.label }}</span>
          <HelpHint v-if="metric.hint || metric.rawPrecision" :text="metric.hint || metric.rawPrecision || ''" />
        </dt>
        <dd :style="{ width: widths?.columns[index]?.value, color: metric.color }" :class="`is-${metric.tone || 'neutral'}`">{{ metric.value }}</dd>
      </div>
    </div>
    <div v-if="summary.supplement" class="stock-quote-summary__supplement">
      <dt :style="{ width: widths?.supplement?.label }">{{ summary.supplement.label }}</dt>
      <dd :style="{ width: widths?.supplement?.value }" :class="`is-${summary.supplement.tone || 'neutral'}`">{{ summary.supplement.value }}</dd>
      <div v-if="summary.supplement.details?.length" class="stock-quote-summary__supplement-details">
        <span v-for="(detail, index) in summary.supplement.details" :key="`${detail.label}-${detail.value}`" :style="{ width: widths?.supplement?.details[index] }">
          {{ detail.value }}
        </span>
      </div>
    </div>
  </AppScrollArea>
</template>

<style scoped>
.stock-quote-summary { --app-scroll-display: flex; --app-scroll-align: stretch; --app-scroll-gap: var(--app-space-2); margin: 0; font-variant-numeric: tabular-nums; }
.stock-quote-summary--gap-relaxed { --app-scroll-gap: var(--stock-quote-section-gap); }
.stock-quote-summary--stable { max-width: 100%; }
.stock-quote-summary__hero { display: flex; flex-shrink: 0; align-items: center; justify-content: center; align-self: stretch; padding-right: var(--app-space-2); border-right: 1px solid var(--app-border-divider); text-align: center; }
.stock-quote-summary__hero-values { display: flex; flex-direction: column; align-items: center; }
.stock-quote-summary__hero-details { display: flex; gap: var(--app-space-2); margin-top: 2px; font-size: var(--app-font-size-caption); white-space: nowrap; }
.stock-quote-summary__hero dt, .stock-quote-summary__metric dt { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); font-weight: var(--app-font-weight-section); }
.stock-quote-summary__hero dd, .stock-quote-summary__metric dd { margin: 0; white-space: nowrap; color: var(--el-text-color-primary); }
.stock-quote-summary__hero dd { font-size: var(--app-font-size-page-title-sm); line-height: var(--app-line-height-data); font-weight: var(--app-font-weight-strong); }
.stock-quote-summary__column { display: flex; flex-shrink: 0; min-width: 0; flex-direction: column; gap: var(--app-space-control-gap); }
.stock-quote-summary__metric { display: flex; justify-content: space-between; gap: var(--app-space-2); line-height: var(--app-line-height-table); }
.stock-quote-summary__metric dt, .stock-quote-summary__metric dd { flex-shrink: 0; }
.stock-quote-summary__metric dt { display: flex; align-items: center; min-width: max-content; gap: var(--app-space-control-gap); white-space: nowrap; }
.stock-quote-summary__metric dd { text-align: right; }
.stock-quote-summary__supplement { display: flex; flex-shrink: 0; min-width: 0; flex-direction: column; justify-content: center; padding-left: var(--stock-quote-section-gap); border-left: 1px solid var(--app-border-divider); }
.stock-quote-summary__supplement dt { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); font-weight: var(--app-font-weight-section); white-space: nowrap; }
.stock-quote-summary__supplement dd { margin: 0; color: var(--el-text-color-primary); font-size: var(--app-font-size-section-title); line-height: var(--app-line-height-data); font-weight: var(--app-font-weight-strong); white-space: nowrap; }
.stock-quote-summary__supplement-details { display: flex; flex-direction: column; color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); white-space: nowrap; }
.stock-quote-summary .is-up { color: var(--market-up-color); }
.stock-quote-summary .is-down { color: var(--market-down-color); }

@container app-viewport (max-width: 720px) {
  .stock-quote-summary:has(.stock-quote-summary__supplement) {
    --app-scroll-wrap: wrap;
  }

  .stock-quote-summary__supplement {
    box-sizing: border-box;
    flex: 1 0 100%;
    flex-direction: row;
    align-items: center;
    gap: var(--app-space-2);
    padding: var(--app-space-2) 0 0;
    border-top: 1px solid var(--app-border-divider);
    border-left: 0;
  }

  .stock-quote-summary__supplement-details {
    margin-left: auto;
    flex-direction: row;
    gap: var(--app-space-2);
  }
}
</style>
