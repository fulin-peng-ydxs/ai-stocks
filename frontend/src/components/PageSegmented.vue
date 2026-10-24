<script setup lang="ts">
import { computed } from 'vue'
type OptionValue = string | number | boolean

const props = defineProps<{
  modelValue: OptionValue
  options: { label: string; value: OptionValue }[]
  /** 稳定自动化测试锚点；只在需要 E2E 覆盖的关键控件上显式传入。 */
  testId?: string
  /** 默认跟随所在页面密度；small / large 仅表达显式尺寸层级。 */
  size?: 'default' | 'small' | 'large'
  /** 页面级模式切换使用 primary；设置型枚举保持 neutral。 */
  tone?: 'neutral' | 'primary'
  /** tabs 用于图表周期等轻量视图切换；保留分段控件行为，仅改为文字与下划线表达。 */
  variant?: 'contained' | 'tabs'
  /** 只读配置仍展示真实选中项，但禁止切换。 */
  disabled?: boolean
}>()

const activeIndex = computed(() => props.options.findIndex(option => option.value === props.modelValue))

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
      'page-segmented--large': props.size === 'large',
      'page-segmented--primary': props.tone === 'primary',
      'page-segmented--tabs': props.variant === 'tabs',
      'page-segmented--disabled': props.disabled,
    }"
    :style="{ '--segment-count': Math.max(1, props.options.length), '--segment-index': Math.max(0, activeIndex) }"
    role="group"
    :aria-disabled="props.disabled || undefined"
    :data-testid="props.testId"
  >
    <span v-if="props.variant === 'tabs' && activeIndex >= 0" class="seg-indicator" aria-hidden="true" />
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
  position: relative;
  box-sizing: border-box;
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(0, 1fr);
  min-width: 0;
  max-width: 100%;
  gap: var(--app-space-1);
  height: var(--app-density-control-height, var(--app-control-height-md));
  padding: 2px;
  border: 1px solid var(--page-settings-section-border);
  border-radius: var(--layout-control-radius);
  background: var(--page-settings-seg-bg);
}
.seg-btn {
  box-sizing: border-box;
  min-width: 0;
  max-width: 100%;
  min-height: 0;
  height: 100%;
  padding: 0 var(--app-space-2);
  border: 1px solid transparent;
  border-radius: var(--app-radius-segment);
  background: transparent;
  color: var(--page-settings-text-subtle);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--app-space-control-gap);
  transition: background-color var(--app-motion-content) var(--app-motion-ease),
    color var(--app-motion-content) var(--app-motion-ease),
    border-color var(--app-motion-content) var(--app-motion-ease),
    box-shadow var(--app-motion-content) var(--app-motion-ease);
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
@media (hover: hover) and (pointer: fine) {
  .seg-btn:hover:not(.active, :disabled) {
    background: var(--page-settings-seg-hover-bg);
    color: var(--page-settings-text);
  }
}
.seg-btn:active:not(:disabled) {
  background: var(--app-button-neutral-pressed-bg);
  color: var(--el-text-color-primary);
}
.seg-btn:focus-visible {
  outline: var(--app-focus-ring);
  outline-offset: -2px;
}
.seg-btn.active {
  background: var(--page-settings-seg-active-bg);
  color: var(--page-settings-text);
  border-color: var(--page-settings-seg-active-border);
  box-shadow: 0 1px 2px rgba(31, 45, 70, 0.1);
}
.seg-btn.active:active:not(:disabled) { background: var(--app-button-neutral-pressed-bg); }
.page-segmented--primary .seg-btn.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary);
  color: var(--el-color-white);
  box-shadow: 0 1px 3px color-mix(in srgb, var(--el-color-primary) 28%, transparent);
}
@media (hover: hover) and (pointer: fine) {
  .page-segmented--primary .seg-btn:hover:not(.active, :disabled) {
    background: var(--app-button-primary-hover-bg);
    color: var(--el-color-primary);
  }
}
.page-segmented--primary .seg-btn:active:not(:disabled) {
  background: var(--app-button-primary-pressed-bg);
  color: var(--el-color-primary);
}
.page-segmented--primary .seg-btn.active:active:not(:disabled) {
  background: var(--app-button-primary-solid-pressed-bg);
  color: var(--el-color-white);
}
.page-segmented--disabled {
  border-color: var(--el-disabled-border-color);
}
.page-segmented--disabled .seg-btn {
  cursor: not-allowed;
}
.page-segmented--disabled .seg-btn:not(.active) {
  color: var(--el-disabled-text-color);
}
/* 与标准命令、输入控件使用相同显式档位，不按所在业务页面重新解释 small。 */
.page-segmented--small { height: var(--app-control-height-sm); }
.page-segmented--large { height: var(--app-control-height-lg); }
.page-segmented--tabs {
  gap: var(--app-segment-gap, var(--app-space-2));
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.page-segmented--tabs .seg-btn {
  position: relative;
  min-height: 0;
  height: 100%;
  padding: 0 var(--app-space-1);
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-regular);
}
.seg-indicator {
  position: absolute;
  pointer-events: none;
  bottom: 0;
  left: 0;
  /* tabs 沿用等分网格；位置由选中值派生，缩放/容器变宽无需尺寸监听。 */
  width: calc((100% - (var(--segment-count) - 1) * var(--app-segment-gap, var(--app-space-2))) / var(--segment-count));
  height: 3px;
  transform: translateX(calc(var(--segment-index) * (100% + var(--app-segment-gap, var(--app-space-2)))));
  transition: transform var(--app-motion-content) var(--app-motion-ease);
}
.seg-indicator::after {
  content: '';
  position: absolute;
  inset: 0 var(--app-space-1);
  border-radius: 999px;
  background: var(--el-text-color-primary);
}
.page-segmented--primary .seg-indicator::after {
  background: var(--el-color-primary);
}

@media (hover: hover) and (pointer: fine) {

  .page-segmented--tabs .seg-btn:hover:not(.active, :disabled),
  .page-segmented--tabs.page-segmented--primary .seg-btn:hover:not(.active, :disabled) {
    background: transparent;
    color: var(--el-text-color-primary);
  }
}
.page-segmented--tabs .seg-btn.active,
.page-segmented--tabs.page-segmented--primary .seg-btn.active {
  border: 0;
  background: transparent;
  box-shadow: none;
  color: var(--el-text-color-primary);
  font-weight: var(--app-font-weight-section);
}
/* tabs 的按下态也保持无底板，覆盖 contained/primary 的按下配方。 */
.page-segmented--tabs .seg-btn:active:not(:disabled),
.page-segmented--tabs.page-segmented--primary .seg-btn:active:not(:disabled) {
  background: transparent;
  color: var(--el-text-color-primary);
}
.page-segmented--tabs .seg-btn:focus-visible {
  outline-offset: -1px;
}
@media (prefers-reduced-motion: reduce) {
  .seg-btn,
  .seg-indicator { transition: none; }
}
</style>
