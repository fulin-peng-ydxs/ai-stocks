<script setup lang="ts">
import { computed, ref } from 'vue'
import { isFixedDecimalInput } from '@/utils/fixedDecimal'
import { formatMoney } from '@/utils/money'

const props = withDefaults(defineProps<{
  modelValue: string | null
  scale?: number
  integerDigits?: number
  disabled?: boolean
  placeholder?: string
  grouped?: boolean
}>(), {
  scale: 2,
  integerDigits: 18,
  disabled: false,
  placeholder: '0.00',
  grouped: false,
})

const emit = defineEmits<{ 'update:modelValue': [value: string | null] }>()
const focused = ref(false)
const displayValue = computed(() => {
  const value = props.modelValue ?? ''
  return props.grouped && !focused.value && value
    ? formatMoney(value, { digits: props.scale, empty: '' })
    : value
})

function update(raw: string): void {
  const ungrouped = raw.replaceAll(',', '')
  if (ungrouped === '') {
    emit('update:modelValue', null)
    return
  }
  const candidate = ungrouped.startsWith('.') ? `0${ungrouped}` : ungrouped
  if (isFixedDecimalInput(candidate, props.scale, props.integerDigits)) {
    emit('update:modelValue', candidate)
  }
}
</script>

<template>
  <el-input
    :model-value="displayValue"
    :disabled="disabled"
    :placeholder="placeholder"
    inputmode="decimal"
    @focus="focused = true"
    @blur="focused = false"
    @update:model-value="update"
  />
</template>
