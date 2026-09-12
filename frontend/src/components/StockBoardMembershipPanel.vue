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
  showIndustries?: boolean
}>(), {
  membership: null,
  loading: false,
  error: '',
  canNavigate: false,
  returnPath: '',
  showIndustries: true,
})

const emit = defineEmits<{ retry: [] }>()
interface MembershipGroup {
  key: 'industry' | 'concept'
  label: string
  items: BoardMembershipItem[]
}

const groups = computed<MembershipGroup[]>(() => [
  ...(props.showIndustries
    ? [{ key: 'industry' as const, label: '所属行业', items: props.membership?.industries ?? [] }]
    : []),
  { key: 'concept', label: '所属概念', items: props.membership?.concepts ?? [] },
])

function winnerCode(type: 'industry' | 'concept'): string | null {
  const related = props.membership?.related_boards
  if (!related || related.unavailable_reason) return null
  return related[type]?.board_code ?? null
}

function isWinner(type: 'industry' | 'concept', item: BoardMembershipItem): boolean {
  return item.board_code === winnerCode(type)
}

</script>

<template>
  <el-card shadow="never" class="stock-board-membership" data-testid="stock-board-membership-card">
    <template #header>
      <div class="stock-board-membership__head">
        <span>所属板块</span>
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
    <div v-else class="stock-board-membership__groups" v-loading="loading && !!membership">
      <section v-for="group in groups" :key="group.key" class="stock-board-membership__group">
        <h4>{{ group.label }}</h4>
        <div v-if="group.items.length" class="stock-board-membership__grid">
          <MarketBoardTag
            v-for="item in group.items"
            :key="item.board_code"
            :name="item.name"
            :pct-chg="item.pct_chg"
            :related="isWinner(group.key, item)"
            :to="canNavigate ? sectorDetailLocation(item.board_code, returnPath) : undefined"
            :data-testid="`stock-board-${item.board_code}`"
          />
        </div>
        <span v-else class="stock-board-membership__empty">暂无{{ group.label }}</span>
      </section>
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
  gap: var(--app-space-2);
}

.stock-board-membership__groups {
  display: grid;
  gap: var(--app-space-3);
}

.stock-board-membership__group h4 {
  margin: 0 0 var(--app-space-2);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-section);
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
