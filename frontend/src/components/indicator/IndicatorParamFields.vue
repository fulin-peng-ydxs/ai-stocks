<script setup lang="ts">
import HelpHint from '@/components/HelpHint.vue'
import type { IndicatorParam } from '@/api/scoreProfile'

const props = defineProps<{
  params: IndicatorParam[]
  modelValue: Record<string, number>
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, number>] }>()

function setValue(name: string, value: number | undefined): void {
  if (value === undefined) return
  emit('update:modelValue', { ...props.modelValue, [name]: value })
}
</script>

<template>
  <span v-for="param in params" :key="param.name" class="indicator-param-field">
    <label>
      {{ param.label }}<small v-if="param.unit">（{{ param.unit }}）</small>
    </label>
    <HelpHint v-if="param.description" :text="param.description" />
    <el-input-number
      :model-value="modelValue[param.name]"
      :disabled="disabled"
      :controls="false"
      :min="param.min ?? undefined"
      :max="param.max ?? undefined"
      :step="param.type === 'int' ? 1 : 0.1"
      size="small"
      class="indicator-param-field__input"
      @update:model-value="(value: number | undefined) => setValue(param.name, value)"
    />
  </span>
</template>

<style scoped>
.indicator-param-field {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-1);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.indicator-param-field label { white-space: nowrap; }
.indicator-param-field small { color: var(--el-text-color-placeholder); }
.indicator-param-field__input { width: 76px; }
</style>
