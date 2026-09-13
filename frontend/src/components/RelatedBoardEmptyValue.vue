<script setup lang="ts">
import type { RelatedBoardEmptyReason } from '@/types/relatedBoards'

withDefaults(defineProps<{
  reason?: RelatedBoardEmptyReason | null
  ariaLabel?: string
  testId?: string
}>(), {
  reason: null,
  ariaLabel: '暂无走势板块',
})
</script>

<template>
  <el-tooltip
    v-if="reason"
    :content="reason.message"
    :trigger="['hover', 'focus']"
    placement="top"
    popper-class="app-wrapping-popper related-board-empty-tooltip"
  >
    <span
      class="related-board-empty-value related-board-empty-value--explained"
      tabindex="0"
      :aria-label="`${ariaLabel}，原因：${reason.message}`"
      :data-testid="testId"
    >—</span>
  </el-tooltip>
  <span
    v-else
    class="related-board-empty-value"
    :aria-label="ariaLabel"
    :data-testid="testId"
  >—</span>
</template>

<style scoped>
.related-board-empty-value {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  color: var(--app-placeholder-text);
  line-height: var(--app-line-height-table);
  text-overflow: ellipsis;
  vertical-align: middle;
  white-space: nowrap;
}

.related-board-empty-value--explained {
  cursor: help;
}

.related-board-empty-value:focus-visible {
  border-radius: var(--el-border-radius-small);
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}
</style>
