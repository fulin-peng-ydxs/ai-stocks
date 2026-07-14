<script setup lang="ts">
withDefaults(defineProps<{
  label: string
  size?: 'xs' | 'sm' | 'md'
  variant?: 'ghost' | 'soft'
  tone?: 'default' | 'primary' | 'danger'
  disabled?: boolean
}>(), {
  size: 'md',
  variant: 'ghost',
  tone: 'default',
  disabled: false,
})

defineEmits<{
  click: [event: MouseEvent]
}>()
</script>

<template>
  <button
    class="app-icon-button"
    :class="[`is-${size}`, `is-${variant}`, `is-${tone}`]"
    type="button"
    :aria-label="label"
    :title="label"
    :disabled="disabled"
    @click="$emit('click', $event)"
  >
    <span class="app-icon-button__glyph" aria-hidden="true">
      <slot />
    </span>
    <slot name="badge" />
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
.app-icon-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.app-icon-button__glyph {
  width: var(--app-icon-button-glyph);
  height: var(--app-icon-button-glyph);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-icon-button-glyph);
  line-height: 1;
}
.app-icon-button__glyph :deep(svg) {
  width: 1em;
  height: 1em;
  display: block;
}
</style>
