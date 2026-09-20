<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ScoreRunRow } from '@/api/scoreProfile'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'
import StockAnalysisPanel from '@/components/StockAnalysisPanel.vue'
import RankedStockResultTable from '@/components/ranked-stock/RankedStockResultTable.vue'
import type { RankedStockColumn } from './types'
import { useStockAnalysisSelection } from '@/composables/useStockAnalysisSelection'
import { PRICE_COMPARE_METRIC_ORDER } from '@/utils/marketCompare'
import type { AuxiliaryChartType } from '@/composables/useStockChartPreferences'
import type { StockChartWorkspaceSample } from '@/components/stock-chart/workspaceOptions'
import type { MasterDetailRatioRuntimeSample } from '@/layout/masterDetailRatioProfiles'

const props = withDefaults(defineProps<{
  rows: ScoreRunRow[]
  columns: RankedStockColumn[]
  title: string
  meta?: string
  runDate?: string
  loading?: boolean
  scoreKeys?: string[]
  labelOf?: (key: string) => string
  returnPath?: string
  border?: boolean
  defaultMasterRatio?: number
  masterRatioProfiles?: unknown
  slot2?: AuxiliaryChartType
  slot3?: AuxiliaryChartType
  heightRatios?: number[]
}>(), {
  meta: '', runDate: '', loading: false, scoreKeys: () => [],
  labelOf: (key: string) => key, returnPath: '', border: false,
  defaultMasterRatio: 45, slot2: 'volume', slot3: 'macd',
  heightRatios: () => [56, 22, 22],
})

const emit = defineEmits<{
  sortChange: [payload: { prop: string; order: string | null }]
  masterRatioSampleChange: [sample: MasterDetailRatioRuntimeSample | undefined]
  ratioDraft: [ratios: number[]]
  ratioCommit: [ratios: number[]]
  workspaceResize: [sample: StockChartWorkspaceSample | undefined]
}>()

const router = useRouter()
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
</script>

<template>
  <MarketMasterDetailWorkspace
    v-model:analysis-visible="analysisVisible"
    eyebrow="评分结果"
    :title="title"
    :meta="meta"
    :default-master-ratio="defaultMasterRatio"
    :master-ratio-profiles="masterRatioProfiles"
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
        adjust-mode="qfq"
        :slot2="slot2"
        :slot3="slot3"
        :height-ratios="heightRatios"
        @activate="selection.activate"
        @remove="selection.remove"
        @open-detail="selection.activeCode.value && router.push(`/stocks/${selection.activeCode.value}`)"
        @ratio-draft="emit('ratioDraft', $event)"
        @ratio-commit="emit('ratioCommit', $event)"
        @workspace-resize="emit('workspaceResize', $event)"
      />
    </template>
  </MarketMasterDetailWorkspace>
</template>
