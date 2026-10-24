<script setup lang="ts">
import { computed } from 'vue'
import AppAsyncRegion from '@/components/AppAsyncRegion.vue'
import MarketBoardTag from '@/components/MarketBoardTag.vue'
import type { BoardMembershipItem, StockBoardMembership } from '@/api/stocks'
import { sectorDetailLocation } from '@/utils/sectorNavigation'

const props = withDefaults(defineProps<{
  membership?: StockBoardMembership | null
  loading?: boolean
  error?: string
  canNavigate?: boolean
  returnPath?: string
}>(), {
  membership: null,
  loading: false,
  error: '',
  canNavigate: false,
  returnPath: '',
})

const emit = defineEmits<{ retry: [] }>()

function winnerCode(type: 'industry' | 'concept'): string | null {
  const related = props.membership?.related_boards
  if (!related || related.unavailable_reason) return null
  return related[type]?.board_code ?? null
}

function isWinner(type: 'industry' | 'concept', item: BoardMembershipItem): boolean {
  return item.board_code === winnerCode(type)
}

const relatedIndustry = computed<BoardMembershipItem | null>(() => {
  const code = winnerCode('industry')
  if (!code) return null
  const membership = props.membership?.industries.find((item) => item.board_code === code)
  if (membership) return membership
  const winner = props.membership?.related_boards?.industry
  return winner
    ? { board_code: winner.board_code, name: winner.name, board_type: 'industry', pct_chg: null }
    : null
})

// 冠军优先，其他板块保留接口顺序；跨类型去重，避免冠军重复出现。
const boards = computed(() => {
  const items = [
    ...(relatedIndustry.value ? [relatedIndustry.value] : []),
    ...(props.membership?.concepts ?? []).filter((item) => isWinner('concept', item)),
    ...(props.membership?.industries ?? []),
    ...(props.membership?.concepts ?? []),
  ]
  return [...new Map(items.map((item) => [item.board_code, item])).values()]
})

</script>

<template>
  <el-card shadow="never" class="stock-board-membership" data-testid="stock-board-membership-card">
    <template #header>
      <span>所属板块</span>
    </template>

    <AppAsyncRegion
      :loading="loading"
      :has-content="Boolean(membership)"
      :error="error"
      state-size="compact"
      loading-title="正在加载所属板块…"
      error-title="所属板块加载失败"
      empty-title="暂无所属板块"
      retry
      @retry="emit('retry')"
    >
      <div class="stock-board-membership__body">
        <div v-if="boards.length" class="stock-board-membership__grid">
          <MarketBoardTag
            v-for="item in boards"
            :key="item.board_code"
            :name="item.name"
            :pct-chg="item.pct_chg"
            :related="isWinner(item.board_type, item)"
            :to="canNavigate ? sectorDetailLocation(item.board_code, returnPath) : undefined"
            :data-testid="isWinner('industry', item)
              ? 'stock-board-related-industry' : `stock-board-${item.board_code}`"
          />
        </div>
        <span v-else class="stock-board-membership__empty">暂无所属板块</span>
      </div>
    </AppAsyncRegion>
  </el-card>
</template>

<style scoped>
.stock-board-membership {
  flex: 0 0 auto;
}

.stock-board-membership__grid {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: var(--app-space-3) var(--app-space-2);
  padding-top: var(--app-space-2);
}

.stock-board-membership__empty {
  color: var(--app-placeholder-text);
  font-size: var(--app-font-size-caption);
}

</style>
