<script setup lang="ts">
import { TrendCharts } from '@element-plus/icons-vue'
import AppIconButton from '@/components/AppIconButton.vue'

withDefaults(defineProps<{
  active?: boolean
  label: string
  disabled?: boolean
  testId?: string
}>(), {
  active: false,
  disabled: false,
  testId: undefined,
})

const emit = defineEmits<{
  toggle: []
}>()
</script>

<template>
  <AppIconButton
    class="compare-pin-button"
    :class="{ 'compare-pin-button--active': active }"
    :label="label"
    :disabled="disabled"
    :data-testid="testId"
    size="xs"
    :native-title="false"
    @click.stop="emit('toggle')"
  >
    <el-icon><TrendCharts /></el-icon>
  </AppIconButton>
</template>

<style scoped>
.compare-pin-button--active {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
</style>
