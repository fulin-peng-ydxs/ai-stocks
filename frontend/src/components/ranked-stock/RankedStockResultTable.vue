<script setup lang="ts">
import AppRowActions from '@/components/AppRowActions.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import RelatedBoardCell from '@/components/RelatedBoardCell.vue'
import ScoreGradeTag from '@/components/ScoreGradeTag.vue'
import StockAnalysisNameCell from '@/components/StockAnalysisNameCell.vue'
import StockStatusTag from '@/components/StockStatusTag.vue'
import SubScoreChips from '@/components/SubScoreChips.vue'
import type { ScoreRunRow } from '@/api/scoreProfile'
import type { RankedStockColumn } from './types'

const props = withDefaults(defineProps<{
  rows: ScoreRunRow[]
  columns: RankedStockColumn[]
  loading?: boolean
  border?: boolean
  height?: string | number
  activeCode?: string
  scoreKeys?: string[]
  labelOf?: (key: string) => string
  returnPath?: string
  stAsOfDate?: string | null
  analysisPins?: boolean
  /** 名称列中由调用方通过 name-leading 提供的紧凑前置控件数量。 */
  nameLeadingControls?: number
  isPinned?: (code: string) => boolean
  rowClass?: (row: ScoreRunRow) => string
  pagination?: {
    currentPage: number
    pageSize: number
    total: number
    pageSizes?: number[]
  }
}>(), {
  loading: false,
  border: false,
  height: '100%',
  activeCode: '',
  scoreKeys: () => [],
  labelOf: (key: string) => key,
  returnPath: '',
  stAsOfDate: null,
  analysisPins: true,
  nameLeadingControls: 0,
  isPinned: () => false,
  rowClass: () => '',
})

const emit = defineEmits<{
  rowClick: [row: ScoreRunRow]
  toggleAnalysis: [row: ScoreRunRow]
  sortChange: [payload: { prop: string; order: string | null }]
  pageChange: [page: number]
  sizeChange: [size: number]
}>()

function rowClassName({ row }: { row: ScoreRunRow }): string {
  return [
    row.code === props.activeCode ? 'stock-analysis-row--active' : '',
    props.rowClass(row),
  ].filter(Boolean).join(' ')
}

function leadingControlsOf(column: RankedStockColumn): number {
  if (column.key !== 'name') return 0
  return props.nameLeadingControls + (props.analysisPins ? 1 : 0)
}
</script>

<template>
  <AppDataTable
    kind="wide-table"
    :data="rows"
    :loading="loading"
    :border="border"
    :height="height"
    :row-class-name="rowClassName"
    :pagination="pagination"
    row-key="code"
    clickable
    @row-click="emit('rowClick', $event)"
    @sort-change="emit('sortChange', $event)"
    @page-change="emit('pageChange', $event)"
    @size-change="emit('sizeChange', $event)"
  >
    <slot name="leading-columns" />
    <AppTableColumn v-if="!columns.some(column => column.key === 'name')" label="操作" role="action-compact">
      <template #default="{ row }">
        <AppRowActions :actions="[{ key: 'view', kind: 'navigation', label: '查看走势', onClick: () => emit('rowClick', row) }]" />
      </template>
    </AppTableColumn>
    <AppTableColumn
      v-for="column in columns"
      :key="column.key"
      :label="column.label"
      :prop="column.key === 'score' ? 'total_score' : column.key"
      :sortable="column.sortable"
      :role="column.role"
      :leading-controls="leadingControlsOf(column)"
    >
      <template #default="{ row }">
        <template v-if="column.key === 'rank'">{{ row.rank ?? '—' }}</template>
        <span v-else-if="column.key === 'code'" class="app-inline-info app-inline-info--nowrap">
          <span>{{ row.code }}</span>
          <StockStatusTag
            v-if="!columns.some((item) => item.key === 'name')"
            :is-st="row.is_st"
            :as-of-date="row.st_as_of_date || stAsOfDate"
          />
        </span>
        <StockAnalysisNameCell
          v-else-if="column.key === 'name' && analysisPins"
          :code="row.code"
          :name="row.name"
          :pinned="isPinned(row.code)"
          :is-st="row.is_st"
          :st-as-of-date="row.st_as_of_date || stAsOfDate"
          @select="emit('rowClick', row)"
          @toggle="emit('toggleAnalysis', row)"
        >
          <template #leading><slot name="name-leading" :row="row" /></template>
        </StockAnalysisNameCell>
        <span v-else-if="column.key === 'name'" class="app-inline-info app-inline-info--nowrap">
          <slot name="name-leading" :row="row" />
          <el-button data-button-kind="navigation" link type="primary" class="app-table-field-link" @click.stop="emit('rowClick', row)">{{ row.name || row.code }}</el-button>
          <StockStatusTag :is-st="row.is_st" :as-of-date="row.st_as_of_date || stAsOfDate" />
        </span>
        <template v-else-if="column.key === 'board'">{{ row.board || '—' }}</template>
        <RelatedBoardCell
          v-else-if="column.key === 'relatedIndustry'"
          :summary="row.related_boards"
          board-type="industry"
          :return-path="returnPath"
        />
        <RelatedBoardCell
          v-else-if="column.key === 'relatedConcept'"
          :summary="row.related_boards"
          board-type="concept"
          :return-path="returnPath"
        />
        <template v-else-if="column.key === 'score'">
          <strong v-if="row.total_score != null" class="score">{{ row.total_score }}</strong>
          <span v-else class="muted">{{ row.score_status === 'excluded_st' ? '该方案未纳入 ST' : '—' }}</span>
        </template>
        <template v-else-if="column.key === 'grade'">
          <ScoreGradeTag v-if="row.grade" :grade="row.grade" /><span v-else class="muted">—</span>
        </template>
        <SubScoreChips
          v-else-if="column.key === 'subScores' && scoreKeys.length"
          :score-keys="scoreKeys"
          :scores="row.sub_scores"
          :label-of="labelOf"
        />
      </template>
    </AppTableColumn>
  </AppDataTable>
</template>
