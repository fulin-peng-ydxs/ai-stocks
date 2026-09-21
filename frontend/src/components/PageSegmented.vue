<script setup lang="ts">
type OptionValue = string | number | boolean

const props = defineProps<{
  modelValue: OptionValue
  options: { label: string; value: OptionValue }[]
  /** 稳定自动化测试锚点；只在需要 E2E 覆盖的关键控件上显式传入。 */
  testId?: string
  /** 紧凑控件行使用 small；设置抽屉与表单保持 default。 */
  size?: 'default' | 'small'
  /** 页面级模式切换使用 primary；设置型枚举保持 neutral。 */
  tone?: 'neutral' | 'primary'
  /** 只读配置仍展示真实选中项，但禁止切换。 */
  disabled?: boolean
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
    :class="{
      'page-segmented--small': props.size === 'small',
      'page-segmented--primary': props.tone === 'primary',
      'page-segmented--disabled': props.disabled,
    }"
    role="group"
    :aria-disabled="props.disabled || undefined"
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
      data-overflow-tooltip-delegate
      :disabled="props.disabled"
      @click="$emit('update:modelValue', option.value)"
    >
      <!-- 可选前置图标（如明暗模式的日/夜/系统状态图形）；不传则保持纯文字。 -->
      <slot name="icon" :option="option" :active="option.value === props.modelValue" />
      <span class="seg-label" data-overflow-tooltip-target>{{ option.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.page-segmented {
  box-sizing: border-box;
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(0, 1fr);
  min-width: 0;
  max-width: 100%;
  gap: var(--app-space-1);
  padding: 3px;
  border: 1px solid var(--page-settings-section-border);
  border-radius: 12px;
  background: var(--page-settings-seg-bg);
}
.seg-btn {
  box-sizing: border-box;
  min-width: 0;
  max-width: 100%;
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
  gap: var(--app-space-control-gap);
  transition: background-color .15s ease, color .15s ease, border-color .15s ease, box-shadow .15s ease;
}
.seg-label {
  display: block;
  flex: 1 1 auto;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
.page-segmented--primary .seg-btn.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary);
  color: var(--el-color-white);
  box-shadow: 0 1px 3px color-mix(in srgb, var(--el-color-primary) 28%, transparent);
}
.page-segmented--primary .seg-btn:hover:not(.active) {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.page-segmented--disabled {
  opacity: .68;
}
.page-segmented--disabled .seg-btn {
  cursor: not-allowed;
}
.page-segmented--small {
  box-sizing: border-box;
  height: var(--app-control-height-md);
  padding: 2px;
  border-radius: var(--layout-control-radius);
}
.page-segmented--small .seg-btn {
  min-height: 0;
  height: 100%;
  padding: 0 var(--app-space-2);
  border-radius: calc(var(--layout-control-radius) - 1px);
}
</style>
