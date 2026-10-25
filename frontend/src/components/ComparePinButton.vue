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
    :aria-pressed="active"
    :label="label"
    :tooltip="label"
    :disabled="disabled"
    :data-testid="testId"
    size="xs"
    @click.stop="emit('toggle')"
  >
    <el-icon><TrendCharts /></el-icon>
  </AppIconButton>
</template>
