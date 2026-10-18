<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import { computed } from 'vue'
import { MARKET_BENCHMARK_OPTIONS } from '@/utils/marketBenchmarks'

const props = withDefaults(defineProps<{
  modelValue: string
  testId?: string
  ariaLabel?: string
}>(), {
  testId: undefined,
  ariaLabel: '对比指数',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const NONE_BENCHMARK_VALUE = '__none__'
const displayOptions = MARKET_BENCHMARK_OPTIONS.map((option) => ({
  ...option,
  value: option.value === '' ? NONE_BENCHMARK_VALUE : option.value,
}))
const displayValue = computed({
  get: () => props.modelValue === '' ? NONE_BENCHMARK_VALUE : props.modelValue,
  set: (value: string) => emit(
    'update:modelValue',
    value === NONE_BENCHMARK_VALUE ? '' : String(value),
  ),
})
</script>

<template>
  <AppSelect
    v-model="displayValue"
    :multiple="false"
    :clearable="false"
    :filterable="false"
    :aria-label="ariaLabel"
    :data-testid="testId"
    width="short"
  >
    <el-option
      v-for="option in displayOptions"
      :key="option.value"
      :label="option.label"
      :value="option.value"
    />
  </AppSelect>
</template>
