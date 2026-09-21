<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ScoreRunRow } from '@/api/scoreProfile'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'
import StockAnalysisPanel from '@/components/StockAnalysisPanel.vue'
import RankedStockResultTable from '@/components/ranked-stock/RankedStockResultTable.vue'
import type { RankedStockColumn } from './types'
import { useStockAnalysisSelection } from '@/composables/useStockAnalysisSelection'
import { useStockSet } from '@/stores/stockSet'
import { PRICE_COMPARE_METRIC_ORDER } from '@/utils/marketCompare'
import type { AuxiliaryChartType } from '@/composables/useStockChartPreferences'
import type { StockChartWorkspaceSample } from '@/components/stock-chart/workspaceOptions'
import type { MasterDetailRatioRuntimeSample } from '@/layout/masterDetailRatioProfiles'
import type { MarketWorkspaceHeightMode } from '@/layout/marketWorkspaceSizing'
import type { StockAdjustMode } from '@/composables/useStockAnalysisSession'

const props = withDefaults(defineProps<{
  /** pageRegistry 反向契约标识：每个消费页必须显式声明其布局事实源。 */
  registryPageKey: string
  /** 行情业务口径必须由消费页设置抽屉提供，禁止组件内部写死。 */
  adjustMode: StockAdjustMode
  rows: ScoreRunRow[]
  columns: RankedStockColumn[]
  title: string
  meta?: string
  runDate?: string
  loading?: boolean
  scoreKeys?: string[]
  labelOf?: (key: string) => string
  returnPath?: string
  collectionLabel?: string
  border?: boolean
  defaultMasterRatio?: number
  masterRatioProfiles?: unknown
  slot2?: AuxiliaryChartType
  slot3?: AuxiliaryChartType
  heightRatios?: number[]
  returnMeasurementMode?: 'latest' | 'range'
  measurementOperationsExpanded?: boolean
  heightMode?: MarketWorkspaceHeightMode
}>(), {
  meta: '', runDate: '', loading: false, scoreKeys: () => [],
  labelOf: (key: string) => key, returnPath: '', collectionLabel: '排名结果', border: false,
  defaultMasterRatio: 45, slot2: 'volume', slot3: 'macd',
  heightRatios: () => [56, 22, 22],
  returnMeasurementMode: 'latest',
  measurementOperationsExpanded: false,
  // 排名结果工作台通常位于筛选/试算等长文档末段，默认自适应剩余空间并内部滚动。
  heightMode: 'adaptive',
})

const emit = defineEmits<{
  sortChange: [payload: { prop: string; order: string | null }]
  masterRatioSampleChange: [sample: MasterDetailRatioRuntimeSample | undefined]
  ratioDraft: [ratios: number[]]
  ratioCommit: [ratios: number[]]
  workspaceResize: [sample: StockChartWorkspaceSample | undefined]
  'update:returnMeasurementMode': [value: 'latest' | 'range']
  'update:measurementOperationsExpanded': [value: boolean]
}>()

const router = useRouter()
const stockSet = useStockSet()
const sourceRows = computed(() => props.rows)
const selection = useStockAnalysisSelection(sourceRows, { maxItems: 6 })
const analysisVisible = ref(true)
const mode = ref<'compare' | 'kline'>('compare')
const compareRange = ref(60)
const compareMetric = ref<'cum'>('cum')
const benchmarkCode = ref('000905.SH')
const klineRange = ref(120)

function selectRow(row: ScoreRunRow): void {
  selection.select(row)
}

function openActiveDetail(): void {
  const activeCode = selection.activeCode.value
  if (!activeCode) return
  const items = props.rows.map((row) => ({ code: row.code, name: row.name }))
  stockSet.setResultSet(items, props.collectionLabel, props.returnPath || '/stocks?restore=1')
  void router.push(`/stocks/${activeCode}`)
}
</script>

<template>
  <MarketMasterDetailWorkspace
    :data-registry-page-key="registryPageKey"
    v-model:analysis-visible="analysisVisible"
    eyebrow="评分结果"
    :title="title"
    :meta="meta"
    :default-master-ratio="defaultMasterRatio"
    :master-ratio-profiles="masterRatioProfiles"
    :height-mode="heightMode"
    analysis-drawer-title="股票走势分析"
    test-id-prefix="ranked-stock"
    @master-ratio-sample-change="emit('masterRatioSampleChange', $event)"
  >
    <template #list>
      <RankedStockResultTable
        :rows="rows"
        :columns="columns"
        :loading="loading"
        :border="border"
        :active-code="selection.activeCode.value"
        :is-pinned="selection.isPinned"
        :score-keys="scoreKeys"
        :label-of="labelOf"
        :return-path="returnPath"
        @row-click="selectRow"
        @toggle-analysis="selection.togglePinned"
        @sort-change="emit('sortChange', $event)"
      >
        <template #leading-columns><slot name="leading-columns" /></template>
        <template #name-leading="scope"><slot name="name-leading" v-bind="scope" /></template>
      </RankedStockResultTable>
    </template>
    <template #analysis>
      <StockAnalysisPanel
        v-model:mode="mode"
        v-model:compare-range="compareRange"
        v-model:compare-metric="compareMetric"
        v-model:benchmark-code="benchmarkCode"
        v-model:kline-range="klineRange"
        :active="selection.activeItem.value"
        :items="selection.items.value"
        :end-date="runDate"
        :compare-metrics="PRICE_COMPARE_METRIC_ORDER"
        :adjust-mode="adjustMode"
        :slot2="slot2"
        :slot3="slot3"
        :height-ratios="heightRatios"
        :return-measurement-mode="returnMeasurementMode"
        :measurement-operations-expanded="measurementOperationsExpanded"
        @update:return-measurement-mode="emit('update:returnMeasurementMode', $event)"
        @update:measurement-operations-expanded="emit('update:measurementOperationsExpanded', $event)"
        @activate="selection.activate"
        @remove="selection.remove"
        @open-detail="openActiveDetail"
        @ratio-draft="emit('ratioDraft', $event)"
        @ratio-commit="emit('ratioCommit', $event)"
        @workspace-resize="emit('workspaceResize', $event)"
      />
    </template>
  </MarketMasterDetailWorkspace>
</template>
