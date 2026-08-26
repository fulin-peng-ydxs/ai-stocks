<script setup lang="ts">
import { computed, watch } from 'vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import { MARKET_BENCHMARK_OPTIONS } from '@/utils/marketBenchmarks'
import {
  PRICE_COMPARE_METRIC_META,
  PRICE_COMPARE_METRIC_ORDER,
  type PriceCompareMetric,
} from '@/utils/marketCompare'

const defaultChartMode = defineModel<'compare' | 'kline'>('defaultChartMode', { required: true })
const compareRange = defineModel<number>('compareRange', { required: true })
const benchmarkCode = defineModel<string>('benchmarkCode', { required: true })
const compareMetrics = defineModel<PriceCompareMetric[]>('compareMetrics', { required: true })
const defaultCompareMetric = defineModel<PriceCompareMetric>('defaultCompareMetric', { required: true })
const showAnalysisPanel = defineModel<boolean>('showAnalysisPanel', { required: true })

const defaultMetricOptions = computed(() => PRICE_COMPARE_METRIC_ORDER.filter(
  (metric) => compareMetrics.value.includes(metric),
))

watch(compareMetrics, (metrics) => {
  if (!metrics.length) {
    compareMetrics.value = ['cum']
    defaultCompareMetric.value = 'cum'
    return
  }
  if (!metrics.includes(defaultCompareMetric.value)) {
    defaultCompareMetric.value = metrics[0]!
  }
}, { deep: true })
</script>

<template>
  <div class="setting-item">
    <div class="setting-label">默认图表模式</div>
    <PageSegmented
      v-model="defaultChartMode"
      aria-label="默认图表模式"
      :options="[
        { label: '走势对比', value: 'compare' },
        { label: 'K线', value: 'kline' },
      ]"
    />
  </div>
  <div class="setting-item">
    <div class="setting-label">默认对比周期</div>
    <el-select v-model="compareRange" style="width: 160px">
      <el-option v-for="days in [5, 10, 20, 60, 120, 250]" :key="days" :value="days" :label="`${days}日`" />
    </el-select>
  </div>
  <div class="setting-item">
    <div class="setting-label">默认对比指数</div>
    <el-select v-model="benchmarkCode" style="width: 160px">
      <el-option v-for="option in MARKET_BENCHMARK_OPTIONS" :key="option.value" :value="option.value" :label="option.label" />
    </el-select>
  </div>
  <div class="setting-item">
    <div class="setting-label">对比指标</div>
    <el-checkbox-group v-model="compareMetrics">
      <el-checkbox v-for="metric in PRICE_COMPARE_METRIC_ORDER" :key="metric" :value="metric">
        {{ PRICE_COMPARE_METRIC_META[metric].label }}
      </el-checkbox>
    </el-checkbox-group>
  </div>
  <div class="setting-item">
    <div class="setting-label">默认对比指标</div>
    <el-select v-model="defaultCompareMetric" style="width: 160px">
      <el-option
        v-for="metric in defaultMetricOptions"
        :key="metric"
        :value="metric"
        :label="PRICE_COMPARE_METRIC_META[metric].label"
      />
    </el-select>
  </div>
  <PageToggleRow v-model="showAnalysisPanel" label="显示走势分析区" />
</template>

<style scoped>
.setting-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.setting-label {
  color: var(--page-settings-text-subtle);
  font-size: var(--app-font-size-caption);
}
</style>
