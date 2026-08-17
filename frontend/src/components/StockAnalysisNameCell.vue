<script setup lang="ts">
import { TrendCharts } from '@element-plus/icons-vue'
import AppIconButton from '@/components/AppIconButton.vue'

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
    <AppIconButton
      v-if="code"
      :class="{ 'stock-analysis-pin--active': pinned }"
      :label="`${pinned ? '移出' : '加入'}走势对比：${name || code}`"
      size="xs"
      :native-title="false"
      @click.stop="emit('toggle')"
    >
      <el-icon><TrendCharts /></el-icon>
    </AppIconButton>
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
.stock-analysis-pin--active {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
</style>
