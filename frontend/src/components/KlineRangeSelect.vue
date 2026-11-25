<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
// K 线快捷范围下拉：选项来自全局偏好 useKlinePrefs，所有看 K 线的页面统一。
import { useKlinePrefs } from '@/composables/useKlinePrefs'

withDefaults(defineProps<{
  modelValue: number
  testId?: string
  /** 常规恢复入口用短枚举容量；图表抽屉内铺满所属字段。 */
  width?: 'short' | 'fill'
}>(), { width: 'short' })
defineEmits<{ 'update:modelValue': [value: number] }>()
const { options } = useKlinePrefs()
</script>

<template>
  <AppSelect
    :model-value="modelValue"
    :width="width"
    :data-testid="testId"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-option v-for="o in options" :key="o.value" :value="o.value" :label="o.label" />
  </AppSelect>
</template>
