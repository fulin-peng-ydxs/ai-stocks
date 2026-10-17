<script setup lang="ts">
import { ref } from 'vue'
import AppHoverInfo from './AppHoverInfo'
import { Loading } from '@element-plus/icons-vue'

withDefaults(defineProps<{
  label: string
  size?: 'xs' | 'sm' | 'md'
  variant?: 'ghost' | 'soft'
  tone?: 'default' | 'primary' | 'danger'
  disabled?: boolean
  loading?: boolean
  tooltip?: string
}>(), {
  size: 'md',
  variant: 'ghost',
  tone: 'default',
  disabled: false,
  loading: false,
  tooltip: undefined,
})

const button = ref<HTMLButtonElement>()

defineEmits<{
  click: [event: MouseEvent]
}>()
</script>

<template>
  <button
    ref="button"
    class="app-icon-button"
    :class="[`is-${size}`, `is-${variant}`, `is-${tone}`, { 'is-loading': loading }]"
    type="button"
    :aria-label="label"
    :aria-busy="loading ? 'true' : undefined"
    :disabled="disabled || loading"
    @click="$emit('click', $event)"
  >
    <span class="app-icon-button__glyph" aria-hidden="true">
      <Loading v-if="loading" class="app-icon-button__loading" />
      <slot v-else />
    </span>
    <slot name="badge" />
    <AppHoverInfo v-if="tooltip && button" :reference="button" :content="tooltip" :disabled="loading" />
  </button>
</template>

<style scoped>
.app-icon-button {
  --app-icon-button-size: 32px;
  --app-icon-button-glyph: 16px;
  position: relative;
  width: var(--app-icon-button-size);
  min-width: var(--app-icon-button-size);
  height: var(--app-icon-button-size);
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--layout-control-radius, 6px);
  background: transparent;
  color: inherit;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    border-color 0.15s ease,
    color 0.15s ease,
    box-shadow 0.15s ease;
}
.app-icon-button.is-xs {
  --app-icon-button-size: 24px;
  --app-icon-button-glyph: 12px;
}
.app-icon-button.is-sm {
  --app-icon-button-size: 28px;
  --app-icon-button-glyph: 14px;
}
.app-icon-button.is-soft {
  border-color: var(--el-border-color);
  background: var(--el-fill-color-extra-light);
}
.app-icon-button:hover:not(:disabled) {
  border-color: var(--el-border-color-darker);
  background: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
}
.app-icon-button.is-primary {
  color: var(--el-color-primary);
}
.app-icon-button.is-danger {
  color: var(--el-color-danger);
}
.app-icon-button.is-primary:hover:not(:disabled) {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
}
.app-icon-button.is-danger:hover:not(:disabled) {
  border-color: var(--el-color-danger-light-5);
  background: var(--el-color-danger-light-9);
}
.app-icon-button:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-primary) 18%, transparent);
}
.app-icon-button:disabled:not(.is-loading) {
  opacity: 0.45;
  cursor: not-allowed;
}
.app-icon-button.is-loading {
  cursor: wait;
}
.app-icon-button__glyph {
  width: var(--app-icon-button-glyph);
  height: var(--app-icon-button-glyph);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-icon-button-glyph);
  line-height: var(--app-line-height-solid);
}
.app-icon-button__glyph :deep(svg) {
  width: 1em;
  height: 1em;
  display: block;
}
.app-icon-button__loading {
  animation: app-icon-button-spin 1s linear infinite;
}
@keyframes app-icon-button-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
