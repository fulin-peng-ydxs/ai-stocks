<script setup lang="ts">
import { isFixedDecimalInput } from '@/utils/fixedDecimal'

const props = withDefaults(defineProps<{
  modelValue: string | null
  scale?: number
  integerDigits?: number
  disabled?: boolean
  placeholder?: string
}>(), {
  scale: 2,
  integerDigits: 18,
  disabled: false,
  placeholder: '0.00',
})

const emit = defineEmits<{ 'update:modelValue': [value: string | null] }>()

function update(raw: string): void {
  if (raw === '') {
    emit('update:modelValue', null)
    return
  }
  const candidate = raw.startsWith('.') ? `0${raw}` : raw
  if (isFixedDecimalInput(candidate, props.scale, props.integerDigits)) {
    emit('update:modelValue', candidate)
  }
}
</script>

<template>
  <el-input
    :model-value="modelValue ?? ''"
    :disabled="disabled"
    :placeholder="placeholder"
    inputmode="decimal"
    @update:model-value="update"
  />
</template>
