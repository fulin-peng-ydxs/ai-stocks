<script setup lang="ts">
import { computed } from 'vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
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

const concepts = computed(() => {
  const items = props.membership?.concepts ?? []
  const winner = winnerCode('concept')
  if (!winner) return items

  const winnerIndex = items.findIndex((item) => item.board_code === winner)
  if (winnerIndex <= 0) return items
  return [items[winnerIndex]!, ...items.slice(0, winnerIndex), ...items.slice(winnerIndex + 1)]
})

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

</script>

<template>
  <el-card shadow="never" class="stock-board-membership" data-testid="stock-board-membership-card">
    <template #header>
      <div class="stock-board-membership__head">
        <span>所属板块</span>
        <MarketBoardTag
          v-if="relatedIndustry"
          :name="relatedIndustry.name"
          :pct-chg="relatedIndustry.pct_chg"
          related
          :show-related-label="false"
          :to="canNavigate
            ? sectorDetailLocation(relatedIndustry.board_code, returnPath)
            : undefined"
          class="stock-board-membership__featured"
          data-testid="stock-board-related-industry"
        />
      </div>
    </template>

    <AppStateBlock
      v-if="error"
      state="error"
      size="compact"
      title="所属板块加载失败"
      :description="error"
      retry
      @retry="emit('retry')"
    />
    <AppStateBlock
      v-else-if="loading && !membership"
      state="loading"
      size="compact"
      title="正在加载所属板块…"
    />
    <div v-else class="stock-board-membership__body" v-loading="loading && !!membership">
      <div v-if="concepts.length" class="stock-board-membership__grid">
        <MarketBoardTag
          v-for="item in concepts"
          :key="item.board_code"
          :name="item.name"
          :pct-chg="item.pct_chg"
          :related="isWinner('concept', item)"
          :to="canNavigate ? sectorDetailLocation(item.board_code, returnPath) : undefined"
          :data-testid="`stock-board-${item.board_code}`"
        />
      </div>
      <span v-else class="stock-board-membership__empty">暂无其他板块</span>
    </div>
  </el-card>
</template>

<style scoped>
.stock-board-membership {
  flex: 0 0 auto;
}

.stock-board-membership__head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--app-space-2);
}

.stock-board-membership__featured {
  margin-left: auto;
}

.stock-board-membership__grid {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-2);
}

.stock-board-membership__empty {
  color: var(--app-placeholder-text);
  font-size: var(--app-font-size-caption);
}

</style>
