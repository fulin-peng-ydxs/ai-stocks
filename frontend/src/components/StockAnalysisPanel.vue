<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowRight, Close } from '@element-plus/icons-vue'
import type { Bar, IndicatorField, IndicatorRow } from '@/api/stocks'
import { getBars, getIndicators } from '@/api/stocks'
import AppIconButton from '@/components/AppIconButton.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import KlineRangeSelect from '@/components/KlineRangeSelect.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import StockCompareChart from '@/components/StockCompareChart.vue'
import StockChartWorkspace from '@/components/stock-chart/StockChartWorkspace.vue'
import { ALL_DAYS } from '@/composables/useKlinePrefs'
import { STOCK_COMPARE_RANGES } from '@/composables/useStockAnalysisSession'
import type { AuxiliaryChartType } from '@/composables/useStockChartPreferences'
import { getErrorMessage } from '@/utils/error'

export interface StockAnalysisItem {
  code: string
  name: string | null
}

const props = defineProps<{
  active: StockAnalysisItem | null
  items: StockAnalysisItem[]
  endDate?: string | null
  mode: 'compare' | 'kline'
  compareRange: number
  klineRange: number
  slot2: AuxiliaryChartType
  slot3: AuxiliaryChartType
  heightRatios: number[]
}>()

const emit = defineEmits<{
  'update:mode': [value: 'compare' | 'kline']
  'update:compareRange': [value: number]
  'update:klineRange': [value: number]
  activate: [code: string]
  remove: [code: string]
  openDetail: []
  ratioDraft: [ratios: number[]]
  ratioCommit: [ratios: number[]]
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
const klineBars = ref<Bar[]>([])
const klineWarmupBars = ref<Bar[]>([])
const klineIndicators = ref<IndicatorRow[]>([])
const indicatorError = ref('')
let requestVersion = 0
let controller: AbortController | null = null

const compareSeries = computed(() => props.items
  .filter((item) => barsByCode.value[item.code]?.length)
  .map((item) => ({
    code: item.code,
    name: item.name || item.code,
    bars: barsByCode.value[item.code]!,
  })))
const failedCount = computed(() => Object.keys(partialErrors.value).length)

function requestLookback(range: number): number {
  return range === ALL_DAYS ? 6000 : Math.max(1, range)
}

function isAbort(errorValue: unknown): boolean {
  const candidate = errorValue as { code?: string; name?: string }
  return candidate?.code === 'ERR_CANCELED' || candidate?.name === 'CanceledError'
}

async function loadCompare(
  targetItems: StockAnalysisItem[] = props.items,
  preserveLoaded = false,
): Promise<void> {
  const version = ++requestVersion
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  error.value = ''
  if (!preserveLoaded) partialErrors.value = {}
  const entries = await Promise.allSettled(targetItems.map(async (item) => {
    const result = await getBars(item.code, {
      adjust: 'qfq',
      lookback: requestLookback(props.compareRange),
      end: props.endDate || undefined,
    }, controller!.signal)
    return [item.code, result.bars] as const
  }))
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
  if (!Object.keys(nextBars).length && Object.keys(nextErrors).length) {
    error.value = '股票走势加载失败'
  }
  loading.value = false
}

function retryFailedCompare(): void {
  const failedItems = props.items.filter((item) => partialErrors.value[item.code])
  if (failedItems.length) void loadCompare(failedItems, true)
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
        adjust: 'qfq',
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
    klineBars.value = []
    return
  }
  if (props.mode === 'compare') void loadCompare()
  else void loadKline()
}

function updateMode(value: unknown): void {
  emit('update:mode', value === 'kline' ? 'kline' : 'compare')
}

watch(
  () => [
    props.mode,
    props.active?.code ?? '',
    props.items.map((item) => item.code).join(','),
    props.endDate ?? '',
    props.compareRange,
    props.klineRange,
  ],
  load,
  { immediate: true },
)

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
            v-if="active"
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
        <p>{{ mode === 'compare' ? `与 ${Math.max(0, items.length - 1)} 只股票比较区间走势` : '查看前复权K线、量能与技术指标' }}</p>
      </div>
      <div class="stock-analysis-controls">
        <el-select
          v-if="mode === 'compare'"
          :model-value="compareRange"
          style="width: 96px"
          data-testid="stock-compare-range"
          @update:model-value="emit('update:compareRange', $event)"
        >
          <el-option v-for="option in COMPARE_RANGE_OPTIONS" :key="option.value" :value="option.value" :label="option.label" />
        </el-select>
        <KlineRangeSelect
          v-else
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

    <div v-if="mode === 'compare' && items.length" class="stock-compare-rail" aria-label="当前对比股票">
      <span class="stock-compare-label">对比队列</span>
      <div
        v-for="item in items"
        :key="item.code"
        class="stock-compare-chip"
        :class="{ active: item.code === active?.code, error: partialErrors[item.code] }"
        :title="partialErrors[item.code] || undefined"
      >
        <el-button
          text
          class="stock-compare-activate"
          :aria-pressed="item.code === active?.code"
          @click="emit('activate', item.code)"
        >
          {{ item.name || item.code }}
        </el-button>
        <AppIconButton
          v-if="item.code !== active?.code || items.length > 1"
          class="stock-chip-remove"
          :label="`移除对比：${item.name || item.code}`"
          size="xs"
          :native-title="false"
          @click="emit('remove', item.code)"
        >
          <el-icon><Close /></el-icon>
        </AppIconButton>
      </div>
      <span v-if="items.length < 6" class="stock-compare-hint">从左侧加入，最多6只</span>
    </div>

    <div class="stock-analysis-stage" v-loading="loading">
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
        :active-code="active?.code"
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
        adjust-label="前复权"
        :macd-state="indicatorError ? 'error' : 'ready'"
        :macd-error="indicatorError"
        :min-height="384"
        :zoom-start="0"
        :zoom-end="100"
        aria-label="股票K线多图联动工作区"
        @ratio-draft="emit('ratioDraft', $event)"
        @ratio-commit="emit('ratioCommit', $event)"
        @retry-macd="loadKline"
      />
    </div>

    <footer class="stock-analysis-footer">
      <span v-if="mode === 'compare'">
        各股票按共同区间首个有效交易点归一为100；{{ failedCount ? `${failedCount}只股票加载失败。` : '用于比较相对强弱，不代表实际价格。' }}
      </span>
      <span v-else>前复权行情；K线、量能和MACD按交易日联动。</span>
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
  </section>
</template>

<style scoped>
.stock-analysis-panel {
  display: flex;
  position: relative;
  flex-direction: column;
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
.stock-compare-rail {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--app-space-control-gap);
  min-height: 42px;
  padding: var(--app-space-2) var(--app-space-3);
  overflow-x: auto;
  border-bottom: 1px solid var(--el-border-color-lighter);
  white-space: nowrap;
}
.stock-compare-label,
.stock-compare-hint {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
}
.stock-compare-chip {
  display: inline-flex;
  align-items: center;
  height: var(--app-control-height-sm);
  padding-left: var(--app-space-2);
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-control-radius);
  background: var(--el-bg-color);
  color: var(--el-text-color-regular);
  font: inherit;
  font-size: var(--app-font-size-caption);
}
.stock-compare-chip:hover,
.stock-compare-chip.active,
.stock-compare-chip:focus-within {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.stock-compare-chip.error {
  border-color: var(--el-color-warning);
}
.stock-compare-activate {
  height: 100%;
  padding: 0 var(--app-space-1) 0 0;
  color: inherit;
  font: inherit;
}
.stock-compare-activate:focus-visible {
  outline: 2px solid var(--el-color-primary-light-5);
  outline-offset: -2px;
}
.stock-chip-remove {
  --app-icon-button-size: 18px;
  --app-icon-button-glyph: 11px;
  border-radius: 50%;
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
@media (max-width: 1180px) {
  .stock-analysis-identity p {
    display: none;
  }
}
@media (max-height: 700px) {
  .stock-analysis-head {
    min-height: 60px;
  }
  .stock-analysis-footer {
    min-height: 36px;
    padding-block: var(--app-space-1);
  }
}
@media (prefers-reduced-motion: reduce) {
  .stock-compare-chip {
    transition: none;
  }
}
</style>
