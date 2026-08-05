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
  <div
    class="page-segmented"
    role="group"
    :data-testid="props.testId"
  >
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
      <!-- 可选前置图标（如明暗模式的日/夜/系统状态图形）；不传则保持纯文字。 -->
      <slot name="icon" :option="option" :active="option.value === props.modelValue" />
      <span class="seg-label">{{ option.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.page-segmented {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: 1fr;
  gap: var(--app-space-1);
  padding: 3px;
  border: 1px solid var(--page-settings-section-border);
  border-radius: 12px;
  background: var(--page-settings-seg-bg);
}
.seg-btn {
  min-height: 38px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--page-settings-text-subtle);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: background-color .15s ease, color .15s ease, border-color .15s ease, box-shadow .15s ease;
}
.seg-btn:hover:not(.active) {
  background: var(--page-settings-seg-hover-bg);
  color: var(--page-settings-text);
}
.seg-btn:focus-visible {
  outline: 2px solid var(--page-settings-accent);
  outline-offset: -2px;
}
.seg-btn.active {
  background: var(--page-settings-seg-active-bg);
  color: var(--page-settings-text);
  border-color: var(--page-settings-seg-active-border);
  box-shadow: 0 1px 2px rgba(31, 45, 70, 0.1);
}
</style>
