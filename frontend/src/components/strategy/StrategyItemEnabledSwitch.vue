<script setup lang="ts">
withDefaults(defineProps<{
  modelValue?: boolean
  disabled?: boolean
  label?: string
}>(), {
  modelValue: true,
  disabled: false,
  label: '是否启用策略项',
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  change: [value: boolean]
}>()

function update(value: boolean) {
  emit('update:modelValue', value)
  emit('change', value)
}
</script>

<template>
  <el-switch
    :model-value="modelValue"
    :disabled="disabled"
    :aria-label="label"
    @update:model-value="update"
  />
</template>
