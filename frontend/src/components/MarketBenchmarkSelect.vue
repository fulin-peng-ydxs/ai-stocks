<script setup lang="ts">
import { computed } from 'vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
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
const controlStyle = computed(() => ({ width: props.width }))
</script>

<template>
  <AppFilterSelect
    v-model="displayValue"
    :options="displayOptions"
    :multiple="false"
    :clearable="false"
    :filterable="false"
    :style="controlStyle"
    :aria-label="ariaLabel"
    :data-testid="testId"
  />
</template>
