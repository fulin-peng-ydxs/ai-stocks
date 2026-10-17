<script setup lang="ts">
import ComparePinButton from '@/components/ComparePinButton.vue'
import StockStatusTag from '@/components/StockStatusTag.vue'

withDefaults(defineProps<{
  code?: string
  name?: string | null
  pinned?: boolean
  isSt?: boolean | null
  stAsOfDate?: string | null
  stContextLabel?: string
  showUnknownSt?: boolean
  stOnlyContext?: boolean
}>(), {
  code: '',
  name: null,
  pinned: false,
  isSt: null,
  stAsOfDate: null,
  stContextLabel: '截至',
  showUnknownSt: false,
  stOnlyContext: false,
})

const emit = defineEmits<{
  select: []
  toggle: []
}>()
</script>

<template>
  <div class="stock-analysis-name-cell">
    <slot name="leading" />
    <ComparePinButton
      v-if="code"
      :active="pinned"
      :label="`${pinned ? '移出' : '加入'}走势对比：${name || code}`"
      @toggle="emit('toggle')"
    />
    <el-button link type="primary" class="stock-analysis-name-cell__name" :aria-label="`查看 ${name || code} 走势或详情`" @click.stop="emit('select')">{{ name || code || '—' }}</el-button>
    <StockStatusTag
      :is-st="isSt"
      :as-of-date="stAsOfDate"
      :context-label="stContextLabel"
      :show-unknown="showUnknownSt"
      :st-only-context="stOnlyContext"
    />
    <slot />
  </div>
</template>

<style scoped>
.stock-analysis-name-cell {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  min-width: 0;
}
</style>
