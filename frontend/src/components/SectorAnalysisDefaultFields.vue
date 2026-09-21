<script setup lang="ts">
import { computed, watch } from 'vue'
import MarketBenchmarkSelect from '@/components/MarketBenchmarkSelect.vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import {
  COMPARE_METRIC_META,
  COMPARE_METRIC_ORDER,
  COMPARE_RANGE_OPTIONS,
  type CompareMetric,
} from '@/utils/sectorCompare'

const defaultChartMode = defineModel<'compare' | 'kline'>('defaultChartMode', { required: true })
const benchmarkCode = defineModel<string>('benchmarkCode', { required: true })
const showAnalysisPanel = defineModel<boolean>('showAnalysisPanel', { required: true })
const compareMetrics = defineModel<CompareMetric[]>('compareMetrics', { required: true })
const defaultCompareMetric = defineModel<CompareMetric>('defaultCompareMetric', { required: true })
const compareWindow = defineModel<number>('compareWindow', { required: true })

const defaultMetricOptions = computed(() => COMPARE_METRIC_ORDER.filter(
  (metric) => compareMetrics.value.includes(metric),
))

watch(compareMetrics, (metrics) => {
  if (!metrics.length) {
    compareMetrics.value = ['cum']
    defaultCompareMetric.value = 'cum'
    return
  }
  if (!metrics.includes(defaultCompareMetric.value)) defaultCompareMetric.value = metrics[0]!
}, { deep: true })
</script>

<template>
  <PageSettingItem label="默认图表模式">
    <PageSegmented
      v-model="defaultChartMode"
      aria-label="默认图表模式"
      :options="[
        { label: '走势对比', value: 'compare' },
        { label: 'K线', value: 'kline' },
      ]"
      test-id="sectors-default-chart-mode"
    />
  </PageSettingItem>
  <PageSettingItem label="默认对比指数">
    <MarketBenchmarkSelect v-model="benchmarkCode" aria-label="默认对比指数" />
  </PageSettingItem>
  <PageToggleRow v-model="showAnalysisPanel" label="显示走势分析区" />
  <PageSettingItem label="展示指标">
    <el-checkbox-group v-model="compareMetrics">
      <el-checkbox v-for="metric in COMPARE_METRIC_ORDER" :key="metric" :value="metric">
        {{ COMPARE_METRIC_META[metric].label }}
      </el-checkbox>
    </el-checkbox-group>
  </PageSettingItem>
  <PageSettingItem label="默认对比指标">
    <el-select v-model="defaultCompareMetric" style="width: 160px">
      <el-option
        v-for="metric in defaultMetricOptions"
        :key="metric"
        :value="metric"
        :label="COMPARE_METRIC_META[metric].label"
      />
    </el-select>
  </PageSettingItem>
  <PageSettingItem label="默认涨跌周期">
    <el-select v-model="compareWindow" style="width: 160px">
      <el-option v-for="option in COMPARE_RANGE_OPTIONS" :key="option.value" :value="option.value" :label="option.label" />
    </el-select>
  </PageSettingItem>
</template>
