<script setup lang="ts">
import { computed } from 'vue'
import { MARKET_BENCHMARK_OPTIONS } from '@/utils/marketBenchmarks'

const props = withDefaults(defineProps<{
  modelValue: string
  width?: string
  testId?: string
  ariaLabel?: string
}>(), {
  width: '160px',
  testId: undefined,
  ariaLabel: '对比指数',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const controlStyle = computed(() => ({ width: props.width }))
</script>

<template>
  <el-select
    :model-value="modelValue"
    :style="controlStyle"
    :aria-label="ariaLabel"
    :data-testid="testId"
    @update:model-value="emit('update:modelValue', String($event))"
  >
    <el-option
      v-for="option in MARKET_BENCHMARK_OPTIONS"
      :key="option.value"
      :value="option.value"
      :label="option.label"
    />
  </el-select>
</template>
