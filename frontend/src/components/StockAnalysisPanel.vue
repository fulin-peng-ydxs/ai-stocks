<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'
import type { Bar, IndicatorField, IndicatorRow } from '@/api/stocks'
import { getBars, getIndicators } from '@/api/stocks'
import { getStockBenchmarkBars } from '@/api/stocks'
import CompareQueueRail from '@/components/CompareQueueRail.vue'
import type { CompareQueueItem } from '@/components/CompareQueueRail.vue'
import MarketCompareMetricStrip from '@/components/MarketCompareMetricStrip.vue'
import MarketBenchmarkSelect from '@/components/MarketBenchmarkSelect.vue'
import type { MarketMetricStripItem } from '@/components/MarketCompareMetricStrip.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import KlineRangeSelect from '@/components/KlineRangeSelect.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import StockCompareChart from '@/components/StockCompareChart.vue'
import StockChartWorkspace from '@/components/stock-chart/StockChartWorkspace.vue'
import StockIntradayDialog from '@/components/stock-chart/StockIntradayDialog.vue'
import type { StockChartWorkspaceSample } from '@/components/stock-chart/workspaceOptions'
import { ALL_DAYS } from '@/composables/useKlinePrefs'
import { useStockIntradayDrilldown } from '@/composables/useStockIntradayDrilldown'
import { STOCK_COMPARE_RANGES } from '@/composables/useStockAnalysisSession'
import type { AuxiliaryChartType } from '@/composables/useStockChartPreferences'
import { getErrorMessage } from '@/utils/error'
import {
  PRICE_COMPARE_METRIC_META,
  priceCompareSetLookback,
  priceMetricWindow,
  priceReturn,
  type PriceCompareMetric,
} from '@/utils/marketCompare'

export interface StockAnalysisItem {
  code: string
  name: string | null
}

const props = withDefaults(defineProps<{
  active: StockAnalysisItem | null
  items: StockAnalysisItem[]
  endDate?: string | null
  mode: 'compare' | 'kline'
  compareRange: number
  compareMetric: PriceCompareMetric
  compareMetrics: PriceCompareMetric[]
  benchmarkCode: string
  klineRange: number
  adjustMode?: '' | 'qfq' | 'hfq'
  slot2: AuxiliaryChartType
  slot3: AuxiliaryChartType
  heightRatios: number[]
  canOpenDetail?: boolean
  refreshRevision?: number
}>(), {
  adjustMode: 'qfq',
  canOpenDetail: true,
  refreshRevision: 0,
})

const emit = defineEmits<{
  'update:mode': [value: 'compare' | 'kline']
  'update:compareRange': [value: number]
  'update:compareMetric': [value: PriceCompareMetric]
  'update:benchmarkCode': [value: string]
  'update:klineRange': [value: number]
  activate: [code: string]
  remove: [code: string]
  openDetail: []
  ratioDraft: [ratios: number[]]
  ratioCommit: [ratios: number[]]
  workspaceResize: [sample: StockChartWorkspaceSample | undefined]
}>()

const MODE_OPTIONS: { label: string; value: 'compare' | 'kline' }[] = [
  { label: '走势对比', value: 'compare' },
  { label: 'K线', value: 'kline' },
]
const COMPARE_RANGE_OPTIONS = STOCK_COMPARE_RANGES.map((value) => ({
  value,
  label: value === ALL_DAYS ? '全部' : `${value}日`,
}))
const MACD_FIELDS = [
  'macd_diff',
  'macd_dea',
  'macd_hist',
  'macd_golden_cross',
  'macd_dead_cross',
] as const satisfies readonly IndicatorField[]

const loading = ref(false)
const error = ref('')
const partialErrors = ref<Record<string, string>>({})
const barsByCode = ref<Record<string, Bar[]>>({})
const benchmarkBars = ref<Bar[]>([])
const benchmarkName = ref('')
const benchmarkError = ref('')
const klineBars = ref<Bar[]>([])
const klineWarmupBars = ref<Bar[]>([])
const klineIndicators = ref<IndicatorRow[]>([])
const indicatorError = ref('')
let requestVersion = 0
let controller: AbortController | null = null
const {
  intradayOpen,
  intradayTradeDate,
  intradayRequestKey,
  openIntraday,
} = useStockIntradayDrilldown(() => props.active?.code)

const compareSeries = computed(() => props.items
  .filter((item) => barsByCode.value[item.code]?.length)
  .map((item) => ({
    code: item.code,
    name: item.name || item.code,
    bars: barsByCode.value[item.code]!,
  })))
const failedCount = computed(() => Object.keys(partialErrors.value).length)
const queueItems = computed<CompareQueueItem[]>(() => props.items.map((item) => ({
  key: item.code,
  label: item.name || item.code,
  active: item.code === props.active?.code,
  error: partialErrors.value[item.code] ?? null,
})))
const activeSeries = computed(() => {
  const active = props.active
  const bars = active ? barsByCode.value[active.code] : null
  return active && bars?.length
    ? { code: active.code, name: active.name || active.code, bars }
    : null
})
const benchmarkSeries = computed(() => props.benchmarkCode && benchmarkBars.value.length
  ? {
      code: props.benchmarkCode,
      name: benchmarkName.value || props.benchmarkCode,
      bars: benchmarkBars.value,
    }
  : null)
const calendarPoints = computed(() => benchmarkBars.value.map((bar) => ({
  date: bar.date,
  close: bar.close,
})))
const adjustLabel = computed(() => (
  props.adjustMode === 'hfq' ? '后复权' : props.adjustMode === 'qfq' ? '前复权' : '不复权'
))

function formatPercent(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

function percentTone(value: number | null): 'up' | 'down' | 'muted' | 'neutral' {
  if (value == null || !Number.isFinite(value)) return 'muted'
  return value > 0 ? 'up' : value < 0 ? 'down' : 'neutral'
}

const metricStripItems = computed<MarketMetricStripItem[]>(() => props.compareMetrics.map((metric) => {
  const window = priceMetricWindow(metric, props.compareRange)
  const value = priceReturn(activeSeries.value, window, calendarPoints.value)
  const rangeLabel = COMPARE_RANGE_OPTIONS.find((option) => option.value === props.compareRange)?.label
  return {
    key: metric,
    label: metric === 'cum'
      ? `${PRICE_COMPARE_METRIC_META[metric].label} · ${rangeLabel ?? `${props.compareRange}日`}`
      : PRICE_COMPARE_METRIC_META[metric].label,
    value: formatPercent(value),
    tone: percentTone(value),
  }
}))

function isAbort(errorValue: unknown): boolean {
  const candidate = errorValue as { code?: string; name?: string }
  return candidate?.code === 'ERR_CANCELED' || candidate?.name === 'CanceledError'
}

async function loadCompare(
  targetItems: StockAnalysisItem[] = props.items,
  preserveLoaded = false,
  reloadCalendar = !preserveLoaded,
): Promise<void> {
  const version = ++requestVersion
  controller?.abort()
  controller = new AbortController()
  const signal = controller.signal
  loading.value = true
  error.value = ''
  if (reloadCalendar) {
    benchmarkError.value = ''
  }
  if (!preserveLoaded) {
    partialErrors.value = {}
  }
  const lookback = priceCompareSetLookback(props.compareMetrics, props.compareRange)
  const entriesPromise = Promise.allSettled(targetItems.map(async (item) => {
    const result = await getBars(item.code, {
      adjust: props.adjustMode,
      lookback,
      end: props.endDate || undefined,
    }, signal)
    return [item.code, result.bars] as const
  }))
  const calendarCode = props.benchmarkCode || '000905.SH'
  const calendarPromise = reloadCalendar
    ? getStockBenchmarkBars(calendarCode, {
        lookback,
        end: props.endDate || undefined,
      }, signal).catch((loadError) => {
        if (!isAbort(loadError) && version === requestVersion) {
          benchmarkError.value = getErrorMessage(loadError, '市场交易日加载失败')
        }
        return null
      })
    : null
  const [entries, calendarResult] = await Promise.all([entriesPromise, calendarPromise])
  if (version !== requestVersion) return
  const nextBars: Record<string, Bar[]> = preserveLoaded ? { ...barsByCode.value } : {}
  const nextErrors: Record<string, string> = preserveLoaded ? { ...partialErrors.value } : {}
  entries.forEach((result, index) => {
    const item = targetItems[index]
    if (!item) return
    if (result.status === 'fulfilled') {
      nextBars[result.value[0]] = result.value[1]
      delete nextErrors[item.code]
    }
    else if (!isAbort(result.reason)) nextErrors[item.code] = getErrorMessage(result.reason, '行情加载失败')
  })
  barsByCode.value = nextBars
  partialErrors.value = nextErrors
  if (reloadCalendar) {
    benchmarkBars.value = calendarResult?.bars ?? []
    benchmarkName.value = calendarResult?.name ?? ''
    if (calendarResult && !calendarResult.bars.length) {
      benchmarkError.value = `${calendarResult.name}在当前区间暂无行情`
    }
  }
  if (!Object.keys(nextBars).length && Object.keys(nextErrors).length) {
    error.value = '股票走势加载失败'
  }
  loading.value = false
}

function retryFailedCompare(): void {
  const failedItems = props.items.filter((item) => partialErrors.value[item.code])
  if (failedItems.length) void loadCompare(failedItems, true)
}

function retryCalendar(): void {
  void loadCompare([], true, true)
}

async function loadKline(): Promise<void> {
  const active = props.active
  if (!active) return
  const version = ++requestVersion
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  error.value = ''
  indicatorError.value = ''
  const lookback = props.klineRange === ALL_DAYS ? 6000 : Math.max(props.klineRange, 1250)
  try {
    const [barsResult, indicatorResult] = await Promise.all([
      getBars(active.code, {
        adjust: props.adjustMode,
        lookback,
        end: props.endDate || undefined,
      }, controller.signal),
      getIndicators(active.code, {
        lookback,
        fields: MACD_FIELDS,
        end: props.endDate || undefined,
      }, controller.signal)
        .catch((indicatorLoadError) => {
          if (!isAbort(indicatorLoadError) && version === requestVersion) {
            indicatorError.value = getErrorMessage(indicatorLoadError, 'MACD指标加载失败，K线与量能不受影响')
          }
          return { code: active.code, indicators: [] }
        }),
    ])
    if (version !== requestVersion) return
    const allBars = barsResult.bars
    klineBars.value = props.klineRange === ALL_DAYS ? allBars : allBars.slice(-props.klineRange)
    klineWarmupBars.value = props.klineRange === ALL_DAYS
      ? []
      : allBars.slice(0, -props.klineRange || undefined)
    klineIndicators.value = indicatorResult.indicators
  } catch (loadError) {
    if (!isAbort(loadError) && version === requestVersion) {
      error.value = getErrorMessage(loadError, 'K线加载失败')
      klineBars.value = []
      klineWarmupBars.value = []
      klineIndicators.value = []
    }
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function load(): void {
  if (!props.active) {
    controller?.abort()
    requestVersion += 1
    loading.value = false
    error.value = ''
    barsByCode.value = {}
    benchmarkBars.value = []
    benchmarkError.value = ''
    klineBars.value = []
    return
  }
  if (props.mode === 'compare') void loadCompare()
  else void loadKline()
}

function updateMode(value: unknown): void {
  emit('update:mode', value === 'kline' ? 'kline' : 'compare')
}

function updateCompareMetric(value: string): void {
  if (props.compareMetrics.includes(value as PriceCompareMetric)) {
    emit('update:compareMetric', value as PriceCompareMetric)
  }
}

watch(
  () => [
    props.mode,
    props.active?.code ?? '',
    props.items.map((item) => item.code).join(','),
    props.endDate ?? '',
    props.compareRange,
    props.compareMetric,
    props.compareMetrics.join(','),
    props.benchmarkCode,
    props.klineRange,
    props.adjustMode,
    props.refreshRevision,
  ],
  load,
  { immediate: true },
)
const hasChartContent = computed(() => (
  props.mode === 'compare' ? compareSeries.value.length > 0 : klineBars.value.length > 0
))

onBeforeUnmount(() => {
  requestVersion += 1
  controller?.abort()
})
</script>

<template>
  <section class="stock-analysis-panel" aria-label="股票走势分析" data-testid="stock-analysis-panel">
    <header class="stock-analysis-head">
      <div class="stock-analysis-identity">
        <div class="stock-analysis-eyebrow">当前观察</div>
        <div class="stock-analysis-title-line">
          <h3>{{ active?.name || '等待选择股票' }}</h3>
          <span v-if="active">{{ active.code }}</span>
          <el-button
            v-if="active && canOpenDetail"
            link
            type="primary"
            class="stock-detail-link"
            data-testid="stock-analysis-open-detail"
            @click="emit('openDetail')"
          >
            查看详情
            <el-icon class="el-icon--right"><ArrowRight /></el-icon>
          </el-button>
        </div>
        <p>{{ mode === 'compare' ? `与 ${Math.max(0, items.length - 1)} 只股票比较区间走势` : `查看${adjustLabel}K线、量能与技术指标` }}</p>
      </div>
      <div class="stock-analysis-controls">
        <div v-if="mode === 'compare'" class="stock-benchmark-control">
          <span>对比指数</span>
          <MarketBenchmarkSelect
            :model-value="benchmarkCode"
            width="160px"
            test-id="stock-analysis-benchmark"
            @update:model-value="emit('update:benchmarkCode', String($event))"
          />
        </div>
        <el-select
          v-if="mode === 'compare' && compareMetric === 'cum'"
          :model-value="compareRange"
          style="width: 96px"
          data-testid="stock-compare-range"
          @update:model-value="emit('update:compareRange', $event)"
        >
          <el-option v-for="option in COMPARE_RANGE_OPTIONS" :key="option.value" :value="option.value" :label="option.label" />
        </el-select>
        <KlineRangeSelect
          v-else-if="mode === 'kline'"
          :model-value="klineRange"
          width="112px"
          test-id="stock-analysis-kline-range"
          @update:model-value="emit('update:klineRange', $event)"
        />
        <PageSegmented
          :model-value="mode"
          :options="MODE_OPTIONS"
          aria-label="图表模式"
          test-id="stock-analysis-mode"
          size="small"
          tone="primary"
          @update:model-value="updateMode"
        />
      </div>
    </header>

    <MarketCompareMetricStrip
      v-if="mode === 'compare' && active"
      :items="metricStripItems"
      :active-key="compareMetric"
      ariaLabel="股票对比指标"
      test-id-prefix="stock-analysis-metric"
      @select="updateCompareMetric"
    />

    <CompareQueueRail
      v-if="mode === 'compare' && items.length"
      :items="queueItems"
      aria-label="当前对比股票"
      hint="从左侧加入，最多6只"
      :max="6"
      @activate="(code) => emit('activate', code)"
      @remove="(code) => emit('remove', code)"
    />

    <div class="stock-analysis-stage" v-loading="loading && hasChartContent">
      <AppStateBlock
        v-if="error"
        state="error"
        :title="mode === 'compare' ? '股票走势加载失败' : 'K线加载失败'"
        :description="error"
        retry
        @retry="load"
      />
      <AppStateBlock
        v-else-if="!active"
        state="empty"
        title="选择一只股票"
        description="点击左侧列表中的任意一行即可查看走势"
      />
      <AppStateBlock
        v-else-if="loading && !hasChartContent"
        state="loading"
        :title="mode === 'compare' ? '正在加载股票走势…' : '正在加载K线数据…'"
      />
      <AppStateBlock
        v-else-if="!loading && mode === 'compare' && benchmarkError"
        state="error"
        title="市场交易日加载失败"
        :description="benchmarkError"
      >
        <template #extra>
          <el-button
            type="primary"
            data-testid="stock-analysis-retry-calendar"
            @click="retryCalendar"
          >
            重试交易日
          </el-button>
        </template>
      </AppStateBlock>
      <AppStateBlock
        v-else-if="!loading && mode === 'compare' && !compareSeries.length"
        state="empty"
        title="暂无走势数据"
        description="当前对比股票在所选区间没有可用行情"
      />
      <AppStateBlock
        v-else-if="!loading && mode === 'kline' && !klineBars.length"
        state="empty"
        title="暂无K线数据"
        description="当前股票在所选区间没有可用行情"
      />
      <StockCompareChart
        v-else-if="mode === 'compare'"
        :series="compareSeries"
        :benchmark="benchmarkSeries"
        :calendar="benchmarkBars"
        :active-code="active?.code"
        :metric="compareMetric"
        :range-days="compareRange"
        fill
      />
      <StockChartWorkspace
        v-else
        class="stock-kline-workspace"
        :bars="klineBars"
        :warmup-bars="klineWarmupBars"
        :indicators="klineIndicators"
        :slot2="slot2"
        :slot3="slot3"
        :height-ratios="heightRatios"
        :adjust-label="adjustLabel"
        :macd-state="indicatorError ? 'error' : 'ready'"
        :macd-error="indicatorError"
        :min-height="384"
        :zoom-start="0"
        :zoom-end="100"
        aria-label="股票K线多图联动工作区"
        enable-intraday-drilldown
        @ratio-draft="emit('ratioDraft', $event)"
        @ratio-commit="emit('ratioCommit', $event)"
        @workspace-resize="emit('workspaceResize', $event)"
        @retry-macd="loadKline"
        @bar-click="openIntraday"
      />
    </div>

    <footer class="stock-analysis-footer">
      <span v-if="mode === 'compare'">
        <template v-if="benchmarkError">{{ benchmarkError }}，统一交易日不可用，暂不展示对比结果。</template>
        <template v-else>{{ benchmarkCode
          ? '各股票与指数按共同基期归零；'
          : '各股票从各自首个有效值起算；'
        }}{{ failedCount ? `${failedCount}只股票加载失败。` : '停牌期间沿用最后有效收盘。' }}</template>
      </span>
      <span v-else>{{ adjustLabel }}行情；K线、量能和MACD按交易日联动。</span>
      <el-button
        v-if="mode === 'compare' && failedCount"
        link
        type="primary"
        data-testid="stock-analysis-retry-partial"
        @click="retryFailedCompare"
      >
        重试失败股票
      </el-button>
    </footer>
    <StockIntradayDialog
      v-if="active"
      v-model="intradayOpen"
      :code="active.code"
      :name="active.name"
      :trade-date="intradayTradeDate"
      :request-key="intradayRequestKey"
    />
  </section>
</template>

<style scoped>
.stock-analysis-panel {
  display: flex;
  position: relative;
  flex-direction: column;
  container-type: inline-size;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
}
.stock-analysis-head {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  min-height: 72px;
  padding: var(--app-space-3) var(--app-space-4);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.stock-analysis-identity {
  min-width: 0;
}
.stock-analysis-eyebrow {
  color: var(--el-color-primary);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
  font-weight: var(--app-font-weight-strong);
  letter-spacing: 0.14em;
}
.stock-analysis-title-line {
  display: flex;
  align-items: baseline;
  gap: var(--app-space-2);
}
.stock-analysis-title-line h3 {
  overflow: hidden;
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-title-md);
  line-height: var(--app-line-height-title-md);
  font-weight: var(--app-font-weight-strong);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stock-analysis-title-line > span {
  color: var(--el-text-color-placeholder);
  font-family: var(--app-font-family-mono);
  font-size: var(--app-font-size-micro);
}
.stock-detail-link {
  flex: 0 0 auto;
  height: auto;
  padding: 0;
  font-size: var(--app-font-size-caption);
}
.stock-analysis-identity p {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}
.stock-analysis-controls {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--app-space-2);
}
.stock-benchmark-control {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  white-space: nowrap;
}
.stock-analysis-stage {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.stock-analysis-stage :deep(.stock-compare-wrap),
.stock-analysis-stage :deep(.stock-compare-chart),
.stock-kline-workspace {
  height: 100%;
}
.stock-analysis-footer {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  min-height: 44px;
  padding: var(--app-space-2) var(--app-space-3);
  border-top: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  gap: var(--app-space-2);
}
.stock-analysis-footer > span {
  flex: 1 1 auto;
}
@container app-viewport (max-width: 1180px) {
  .stock-analysis-head {
    align-items: flex-start;
    flex-direction: column;
  }
  .stock-analysis-controls {
    width: 100%;
    flex-wrap: wrap;
  }
  .stock-analysis-identity p {
    display: none;
  }
  .stock-benchmark-control > span {
    display: none;
  }
}
@container (max-width: 700px) {
  .stock-analysis-head {
    align-items: flex-start;
    flex-direction: column;
  }
  .stock-analysis-controls {
    width: 100%;
    flex-wrap: wrap;
  }
  .stock-analysis-identity p,
  .stock-benchmark-control > span {
    display: none;
  }
}
@container app-viewport (max-height: 700px) {
  .stock-analysis-head {
    min-height: 60px;
  }
  .stock-analysis-footer {
    min-height: 36px;
    padding-block: var(--app-space-1);
  }
}
</style>
