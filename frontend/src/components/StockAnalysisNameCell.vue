<script setup lang="ts">
import ComparePinButton from '@/components/ComparePinButton.vue'

withDefaults(defineProps<{
  code?: string
  name?: string | null
  pinned?: boolean
}>(), {
  code: '',
  name: null,
  pinned: false,
})

const emit = defineEmits<{
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
    <span>{{ name || '—' }}</span>
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
