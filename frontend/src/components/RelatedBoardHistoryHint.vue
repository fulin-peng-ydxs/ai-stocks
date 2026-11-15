<script setup lang="ts">
import { formatDateOnly } from '@/utils/dateTime'
import type { RelatedBoardHistory } from '@/types/relatedBoards'
import AppStatusDot from '@/components/AppStatusDot.vue'

withDefaults(defineProps<{
  history?: RelatedBoardHistory | null
  /** 表格已由整体 popover 解释来源时，避免同时弹出第二个提示。 */
  explain?: boolean
}>(), { explain: true })
</script>

<template>
  <AppStatusDot
    v-if="history"
    class="related-board-history-hint"
    :disabled="!explain"
    :content="`当日共同有效样本不足，沿用 ${formatDateOnly(history.as_of_date)} 的最近有效结果`"
    :label="`历史结果，来源日期 ${formatDateOnly(history.as_of_date)}，当日共同有效样本不足`"
  />
</template>
