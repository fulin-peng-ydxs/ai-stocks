<script setup lang="ts">
import AppDataTable from '@/components/AppDataTable.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import RelatedBoardCell from '@/components/RelatedBoardCell.vue'
import ScoreGradeTag from '@/components/ScoreGradeTag.vue'
import StockAnalysisNameCell from '@/components/StockAnalysisNameCell.vue'
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
  analysisPins?: boolean
  isPinned?: (code: string) => boolean
  rowClass?: (row: ScoreRunRow) => string
}>(), {
  loading: false,
  border: false,
  height: '100%',
  activeCode: '',
  scoreKeys: () => [],
  labelOf: (key: string) => key,
  returnPath: '',
  analysisPins: true,
  isPinned: () => false,
  rowClass: () => '',
})

const emit = defineEmits<{
  rowClick: [row: ScoreRunRow]
  toggleAnalysis: [row: ScoreRunRow]
  sortChange: [payload: { prop: string; order: string | null }]
}>()

function rowClassName({ row }: { row: ScoreRunRow }): string {
  return [
    row.code === props.activeCode ? 'stock-analysis-row--active' : '',
    props.rowClass(row),
  ].filter(Boolean).join(' ')
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
    row-key="code"
    clickable
    @row-click="emit('rowClick', $event)"
    @sort-change="emit('sortChange', $event)"
  >
    <slot name="leading-columns" />
    <AppTableColumn
      v-for="column in columns"
      :key="column.key"
      :label="column.label"
      :prop="column.key === 'score' ? 'total_score' : column.key"
      :sortable="column.sortable"
      :role="column.key === 'rank' ? 'rank' : column.key === 'name' ? 'entity' : undefined"
    >
      <template #default="{ row }">
        <template v-if="column.key === 'rank'">{{ row.rank ?? '—' }}</template>
        <template v-else-if="column.key === 'code'">{{ row.code }}</template>
        <StockAnalysisNameCell
          v-else-if="column.key === 'name' && analysisPins"
          :code="row.code"
          :name="row.name"
          :pinned="isPinned(row.code)"
          :tone="row.is_st ? 'warning' : 'default'"
          @toggle="emit('toggleAnalysis', row)"
        >
          <template #leading><slot name="name-leading" :row="row" /></template>
        </StockAnalysisNameCell>
        <span v-else-if="column.key === 'name'" class="app-inline-info app-inline-info--nowrap">
          <slot name="name-leading" :row="row" />
          <span :class="{ 'ranked-stock-name--st': row.is_st }">{{ row.name || '—' }}</span>
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

<style scoped>
.ranked-stock-name--st {
  color: var(--app-warning-text);
  font-weight: var(--app-font-weight-section);
}
</style>
