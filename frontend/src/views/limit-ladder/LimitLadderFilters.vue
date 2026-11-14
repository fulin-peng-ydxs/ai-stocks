<script setup lang="ts">
/** 工作台外部的整页筛选操作栏；条件与排序仍由页面统一持有。 */
import { computed, ref, watch } from 'vue'
import AppAdvancedSearch from '@/components/AppAdvancedSearch.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import AppFilterSwitch from '@/components/AppFilterSwitch.vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppSortControl from '@/components/AppSortControl.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import { DEFAULT_LIMIT_LADDER_FILTERS, LIMIT_LADDER_BOARD_OPTIONS, type LimitLadderFilters } from '@/api/limitLadder'
import { DEFAULT_LIMIT_LADDER_CARD_SORT, DEFAULT_LIMIT_LADDER_CARD_SORT_ORDER, LIMIT_LADDER_CARD_SORT_OPTIONS, type LimitLadderCardSort, type LimitLadderCardSortOrder } from './sorting'

const props = withDefaults(defineProps<{
  filters: LimitLadderFilters
  tradeDate: string | null
  cardSort?: LimitLadderCardSort
  cardSortOrder?: LimitLadderCardSortOrder
}>(), { cardSort: DEFAULT_LIMIT_LADDER_CARD_SORT, cardSortOrder: DEFAULT_LIMIT_LADDER_CARD_SORT_ORDER })
const emit = defineEmits<{
  'update:filters': [filters: LimitLadderFilters]
  'update:tradeDate': [tradeDate: string | null]
  'update:cardSort': [sort: LimitLadderCardSort]
  'update:cardSortOrder': [order: LimitLadderCardSortOrder]
}>()
const keywordDraft = ref(props.filters.keyword)
watch(() => props.filters.keyword, (value) => { keywordDraft.value = value })
const windowOptions = [10, 20, 31, 60].map((value) => ({ label: `${value}日`, value }))
const hasFilters = computed(() => (
  props.filters.window !== DEFAULT_LIMIT_LADDER_FILTERS.window
  || props.filters.ignoreSt !== DEFAULT_LIMIT_LADDER_FILTERS.ignoreSt
  || props.filters.oneWordOnly !== DEFAULT_LIMIT_LADDER_FILTERS.oneWordOnly
  || props.filters.keyword.trim() !== DEFAULT_LIMIT_LADDER_FILTERS.keyword
  || props.filters.hotspotType !== DEFAULT_LIMIT_LADDER_FILTERS.hotspotType
  || props.filters.hotspotKey !== DEFAULT_LIMIT_LADDER_FILTERS.hotspotKey
  || props.filters.boards.join(',') !== DEFAULT_LIMIT_LADDER_FILTERS.boards.join(',')
))
function updateFilters(patch: Partial<LimitLadderFilters>): void {
  emit('update:filters', { ...props.filters, ...patch })
}
function updateBoards(value: string[] | string): void {
  const boards = (Array.isArray(value) ? value : [value]) as LimitLadderFilters['boards']
  updateFilters({
    boards: boards.length ? boards : [...DEFAULT_LIMIT_LADDER_FILTERS.boards],
  })
}
function updateCardSort(value: string): void {
  emit('update:cardSort', value as LimitLadderCardSort)
}
function updateCardSortOrder(value: 'asc' | 'desc'): void {
  emit('update:cardSortOrder', value as LimitLadderCardSortOrder)
}
function searchKeyword(): void {
  updateFilters({ keyword: keywordDraft.value.trim() })
}
function resetFilters(): void {
  keywordDraft.value = ''
  emit('update:filters', { ...DEFAULT_LIMIT_LADDER_FILTERS })
}
</script>

<template>
  <el-card shadow="never" class="filter-card" aria-label="连板天梯筛选" data-testid="limit-ladder-filters">
    <AppAdvancedSearch
      group="ladder"
      :states="{
        boards: { value: filters.boards, options: LIMIT_LADDER_BOARD_OPTIONS, active: filters.boards.length !== LIMIT_LADDER_BOARD_OPTIONS.length, clear: () => updateBoards([]) },
        ignoreSt: { selfLabelled: true, value: filters.ignoreSt, clear: () => updateFilters({ignoreSt:false}) },
        oneWord: { selfLabelled: true, value: filters.oneWordOnly, clear: () => updateFilters({oneWordOnly:false}) },
        keyword: { value: keywordDraft, clear: () => { keywordDraft = ''; searchKeyword() } }
      }"
    >
      <template #context>
        <div class="app-control-width-long">
          <TradeDatePicker :model-value="tradeDate" placeholder="选择交易日" data-testid="limit-ladder-date" @update:model-value="$emit('update:tradeDate',$event)" />
        </div>
        <PageSegmented class="limit-ladder__window" :model-value="filters.window" :options="windowOptions" tone="primary" test-id="limit-ladder-window" aria-label="统计窗口" @update:model-value="updateFilters({window:Number($event) as LimitLadderFilters['window']})" />
      </template>
      <template #boards>
        <AppFilterSelect :model-value="filters.boards" :options="LIMIT_LADDER_BOARD_OPTIONS" :visible-tag-count="2" all-selected-label="全部板块" placeholder="上市板块" aria-label="按上市板块筛选" data-testid="limit-ladder-boards" @change="updateBoards" />
      </template>
      <template #ignoreSt>
        <AppFilterSwitch :model-value="filters.ignoreSt" label="忽略 ST" test-id="limit-ladder-ignore-st" @update:model-value="updateFilters({ignoreSt:$event})" />
      </template>
      <template #oneWord>
        <AppFilterSwitch :model-value="filters.oneWordOnly" label="仅一字板" test-id="limit-ladder-one-word" @update:model-value="updateFilters({oneWordOnly:$event})" />
      </template>
      <template #keyword>
        <AppSearchInput v-model="keywordDraft" class="app-control-width-medium" placeholder="代码 / 名称" data-testid="limit-ladder-keyword" @search="searchKeyword" />
      </template>
      <template #commands>
        <el-button class="limit-ladder__command" data-testid="limit-ladder-reset" :disabled="!hasFilters" @click="resetFilters">重置筛选</el-button>
        <AppSortControl
          :model-value="cardSort"
          :order="cardSortOrder"
          :options="LIMIT_LADDER_CARD_SORT_OPTIONS"
          aria-label="卡片层内排序"
          test-id="limit-ladder-card-sort"
          @update:model-value="updateCardSort"
          @update:order="updateCardSortOrder"
        />
      </template>
    </AppAdvancedSearch>
  </el-card>
</template>

<style scoped>
.limit-ladder__command { flex: 0 0 auto; }
</style>
