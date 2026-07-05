<script setup lang="ts">
import { computed } from 'vue'

export interface AppFilterSelectOption {
  value: string
  label: string
}

const props = withDefaults(defineProps<{
  modelValue?: string[] | string | null
  options: AppFilterSelectOption[]
  placeholder?: string
  multiple?: boolean
  clearable?: boolean
  filterable?: boolean
  collapseTags?: boolean
  disabled?: boolean
}>(), {
  placeholder: '请选择',
  multiple: true,
  clearable: true,
  filterable: true,
  collapseTags: true,
  disabled: false,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[] | string): void
  (e: 'change', value: string[] | string): void
}>()

function toMulti(value: string[] | string | null | undefined): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean)
  const text = String(value ?? '').trim()
  return text ? [text] : []
}

const selected = computed<string[] | string>({
  get() {
    if (props.multiple) return toMulti(props.modelValue)
    return Array.isArray(props.modelValue) ? props.modelValue[0] ?? '' : String(props.modelValue ?? '')
  },
  set(value) {
    emit('update:modelValue', props.multiple ? toMulti(value) : String(Array.isArray(value) ? value[0] ?? '' : value ?? ''))
  },
})

function onChange(value: string[] | string) {
  emit('change', props.multiple ? toMulti(value) : String(Array.isArray(value) ? value[0] ?? '' : value ?? ''))
}
</script>

<template>
  <el-select
    v-model="selected"
    class="app-filter-select"
    :multiple="multiple"
    :clearable="clearable"
    :filterable="filterable"
    :collapse-tags="multiple && collapseTags"
    :collapse-tags-tooltip="multiple && collapseTags"
    :fit-input-width="true"
    :disabled="disabled"
    :placeholder="placeholder"
    @change="onChange"
  >
    <el-option
      v-for="item in options"
      :key="item.value"
      :label="item.label"
      :value="item.value"
    />
  </el-select>
</template>

<style scoped>
.app-filter-select {
  width: 100%;
  min-width: 0;
}
</style>
