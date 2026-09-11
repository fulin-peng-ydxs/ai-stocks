<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getIntraday, type StockIntraday } from '@/api/stocks'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import { getErrorMessage } from '@/utils/error'
import { formatAmount, formatChartNumber, formatVolumeLots } from './chartUtils'
import StockIntradayChart from './StockIntradayChart.vue'
import StockQuoteSummary from './StockQuoteSummary.vue'
import type { StockQuoteSummaryModel, StockQuoteTone } from './stockQuoteSummary'

const props = defineProps<{
  modelValue: boolean
  code: string
  name: string | null
  tradeDate: string
  requestKey?: number
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const loading = ref(false)
const error = ref('')
const data = ref<StockIntraday | null>(null)
let controller: AbortController | null = null
let requestVersion = 0

const title = computed(() => `${props.name || props.code} ${props.code} · ${props.tradeDate} · 分时`)
const rangeDescription = computed(() => {
  const start = data.value?.supported_start
  const end = data.value?.supported_end
  return start && end
    ? `免费分钟源当前仅支持本地最近交易日（${start} 至 ${end}）`
    : '免费分钟源当前仅支持本地最近 8 个交易日'
})
const summary = computed<StockQuoteSummaryModel | null>(() => {
  if (!data.value || !['ready', 'partial'].includes(data.value.status) || !data.value.points.length) {
    return null
  }
  const points = data.value.points
  const last = points.at(-1)!
  const open = points[0]!.open
  const high = Math.max(...points.map((point) => point.high))
  const low = Math.min(...points.map((point) => point.low))
  const volume = points.reduce((total, point) => total + point.volume, 0)
  const amount = points.reduce((total, point) => total + point.amount, 0)
  const pct = data.value.pre_close && data.value.pre_close > 0
    ? ((last.close / data.value.pre_close) - 1) * 100
    : null
  const tone: StockQuoteTone = pct == null || pct === 0 ? 'neutral' : pct > 0 ? 'up' : 'down'
  const amplitude = data.value.pre_close && data.value.pre_close > 0
    ? ((high - low) / data.value.pre_close) * 100
    : null
  return {
    hero: { label: '', value: formatChartNumber(last.close, 2), tone },
    rowsPerColumn: 2,
    metrics: [
      { label: '开盘', value: formatChartNumber(open, 2) },
      { label: '最高', value: formatChartNumber(high, 2) },
      { label: '最低', value: formatChartNumber(low, 2) },
      { label: '涨幅', value: pct == null ? '--' : `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`, tone },
      { label: '振幅', value: amplitude == null ? '--' : `${amplitude.toFixed(2)}%` },
      { label: '换手率', value: data.value.turnover_rate == null ? '--' : `${data.value.turnover_rate.toFixed(2)}%` },
      { label: '成交量', value: formatVolumeLots(volume) },
      { label: '成交额', value: formatAmount(amount) },
    ],
  }
})

function isCanceled(value: unknown): boolean {
  const candidate = value as { code?: string; name?: string }
  return candidate?.code === 'ERR_CANCELED' || candidate?.name === 'CanceledError'
}

async function load(): Promise<void> {
  controller?.abort()
  if (!props.modelValue || !props.code || !props.tradeDate) return
  const version = ++requestVersion
  const nextController = new AbortController()
  controller = nextController
  loading.value = true
  error.value = ''
  data.value = null
  try {
    const result = await getIntraday(props.code, props.tradeDate, nextController.signal)
    if (version === requestVersion && !nextController.signal.aborted) data.value = result
  } catch (reason) {
    if (version === requestVersion && !isCanceled(reason)) {
      error.value = getErrorMessage(reason, '分时行情加载失败，请稍后重试')
    }
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function close(): void {
  controller?.abort()
  requestVersion += 1
  emit('update:modelValue', false)
}

watch(
  [() => props.modelValue, () => props.code, () => props.tradeDate, () => props.requestKey],
  ([open]) => {
    if (open) void load()
    else controller?.abort()
  },
  { immediate: true },
)

onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="min(92vw, 1040px)"
    top="5vh"
    destroy-on-close
    data-testid="stock-intraday-dialog"
    @close="close"
  >
    <template #header>
      <div class="stock-intraday-dialog__header">
        <div class="stock-intraday-dialog__identity">
          <strong>{{ name || code }}</strong>
          <span>{{ code }} · {{ tradeDate }}</span>
        </div>
        <StockQuoteSummary v-if="summary" class="stock-intraday-dialog__summary" :summary="summary" />
      </div>
    </template>
    <AppStateBlock
      v-if="loading"
      state="loading"
      title="正在加载分时行情…"
      description="首次加载会访问免费分钟行情源，后续优先使用 12 小时缓存"
    />
    <AppStateBlock
      v-else-if="error"
      state="error"
      title="分时行情暂时不可用"
      :description="error"
      retry
      @retry="load"
    />
    <AppStateBlock
      v-else-if="data?.status === 'out_of_range'"
      state="empty"
      title="该日期超出免费源范围"
      :description="rangeDescription"
    />
    <AppStateBlock
      v-else-if="data?.status === 'no_data'"
      state="empty"
      title="该交易日暂无分时数据"
      description="可能为停牌、源端暂未覆盖或当日没有成交"
    />
    <template v-else-if="data && (data.status === 'ready' || data.status === 'partial')">
      <AppStatusNotice
        v-if="data.status === 'partial'"
        class="stock-intraday-dialog__notice"
        tone="warning"
        title="免费源返回的分钟点可能不完整，图中仅展示真实数据"
        description="可继续查看现有分时；缺失分钟不会补造价格或成交量"
      />
      <StockIntradayChart :points="data.points" :pre-close="data.pre_close" />
    </template>
  </el-dialog>
</template>

<style scoped>
.stock-intraday-dialog__notice {
  margin-bottom: var(--app-space-3);
}

.stock-intraday-dialog__header {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-5);
  padding-right: var(--app-space-5);
}

.stock-intraday-dialog__identity {
  display: flex;
  min-width: 0;
  align-items: baseline;
  gap: var(--app-space-2);
  white-space: nowrap;
}

.stock-intraday-dialog__identity strong {
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-page-title);
  font-weight: var(--app-font-weight-strong);
  line-height: var(--app-line-height-page-title);
}

.stock-intraday-dialog__identity span {
  color: var(--el-text-color-secondary);
}

.stock-intraday-dialog__summary {
  flex: 0 0 auto;
}

@media (max-width: 960px) {
  .stock-intraday-dialog__header {
    align-items: flex-start;
    flex-direction: column;
    gap: var(--app-space-2);
  }

  .stock-intraday-dialog__summary {
    width: 100%;
    flex-basis: auto;
    gap: var(--app-space-2);
  }
}

</style>
