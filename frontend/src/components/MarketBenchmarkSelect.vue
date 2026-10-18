<script setup lang="ts">
import { computed } from 'vue'
import { MARKET_BENCHMARK_OPTIONS } from '@/utils/marketBenchmarks'
import {
  APP_BOTTOM_FLOATING_FALLBACKS,
  APP_BOTTOM_FLOATING_PLACEMENT,
} from '@/utils/floatingPlacement'

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
  <el-select
    v-model="displayValue"
    class="app-control-width-short"
    :multiple="false"
    :clearable="false"
    :filterable="false"
    :fit-input-width="false"
    :placement="APP_BOTTOM_FLOATING_PLACEMENT"
    :fallback-placements="APP_BOTTOM_FLOATING_FALLBACKS"
    :aria-label="ariaLabel"
    :data-testid="testId"
  >
    <el-option
      v-for="option in displayOptions"
      :key="option.value"
      :label="option.label"
      :value="option.value"
    />
  </el-select>
</template>
