<script setup lang="ts">
type OptionValue = string | number | boolean

const props = defineProps<{
  modelValue: OptionValue
  options: { label: string; value: OptionValue }[]
  /** 稳定自动化测试锚点；只在需要 E2E 覆盖的关键控件上显式传入。 */
  testId?: string
}>()

defineEmits<{
  'update:modelValue': [value: OptionValue]
}>()

function optionTestId(value: OptionValue): string | undefined {
  return props.testId ? `${props.testId}-${String(value)}` : undefined
}
</script>

<template>
  <div class="page-segmented" :data-testid="props.testId">
    <button
      v-for="option in props.options"
      :key="String(option.value)"
      type="button"
      class="seg-btn"
      :class="{ active: option.value === props.modelValue }"
      :aria-pressed="option.value === props.modelValue"
      :data-testid="optionTestId(option.value)"
      @click="$emit('update:modelValue', option.value)"
    >
      {{ option.label }}
    </button>
  </div>
</template>

<style scoped>
.page-segmented {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: 1fr;
  gap: var(--app-space-control-gap);
}
.seg-btn {
  min-height: 38px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: var(--page-settings-seg-bg);
  color: var(--page-settings-text-subtle);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  cursor: pointer;
  transition: background-color .15s ease, color .15s ease, border-color .15s ease;
}
.seg-btn:hover {
  background: var(--page-settings-seg-hover-bg);
  color: var(--page-settings-text);
}
.seg-btn.active {
  background: var(--page-settings-seg-active-bg);
  color: var(--page-settings-text);
  border-color: var(--page-settings-seg-active-border);
  box-shadow: 0 1px 2px rgba(31, 45, 70, 0.1);
}
</style>
