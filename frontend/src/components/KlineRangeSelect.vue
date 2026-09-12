<script setup lang="ts">
// K 线快捷范围下拉：选项来自全局偏好 useKlinePrefs，所有看 K 线的页面统一。
import { useKlinePrefs } from '@/composables/useKlinePrefs'
import {
  APP_BOTTOM_FLOATING_FALLBACKS,
  APP_BOTTOM_FLOATING_PLACEMENT,
} from '@/utils/floatingPlacement'

defineProps<{ modelValue: number; width?: string; testId?: string }>()
defineEmits<{ 'update:modelValue': [value: number] }>()
const { options } = useKlinePrefs()
</script>

<template>
  <el-select
    :model-value="modelValue"
    :style="{ width: width || '130px' }"
    :data-testid="testId"
    :placement="APP_BOTTOM_FLOATING_PLACEMENT"
    :fallback-placements="APP_BOTTOM_FLOATING_FALLBACKS"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-option v-for="o in options" :key="o.value" :value="o.value" :label="o.label" />
  </el-select>
</template>
