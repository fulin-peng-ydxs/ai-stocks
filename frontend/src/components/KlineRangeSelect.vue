<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
// K 线快捷范围下拉：选项来自全局偏好 useKlinePrefs，所有看 K 线的页面统一。
import { useKlinePrefs } from '@/composables/useKlinePrefs'

defineProps<{ modelValue: number; width?: string; testId?: string }>()
defineEmits<{ 'update:modelValue': [value: number] }>()
const { options } = useKlinePrefs()
</script>

<template>
  <AppSelect
    :model-value="modelValue"
    :style="{ width: width || '130px' }"
    :data-testid="testId"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-option v-for="o in options" :key="o.value" :value="o.value" :label="o.label" />
  </AppSelect>
</template>
