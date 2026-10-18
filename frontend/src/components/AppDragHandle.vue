<script setup lang="ts">
import AppIconButton from './AppIconButton.vue'

withDefaults(defineProps<{
  label: string
  active?: boolean
  disabled?: boolean
  describedby?: string
}>(), { active: false, disabled: false, describedby: undefined })
defineEmits<{
  pointerdown: [event: PointerEvent]
  keydown: [event: KeyboardEvent]
  blur: [event: FocusEvent]
  lostpointercapture: [event: PointerEvent]
}>()
</script>

<template>
  <AppIconButton
    class="app-drag-handle"
    size="sm"
    :tone="active ? 'primary' : 'default'"
    :label="`拖动排序：${label}`"
    tooltip="拖动调整顺序；也可按空格后用方向键移动"
    :disabled="disabled"
    :aria-describedby="describedby"
    :aria-pressed="active"
    @pointerdown="$emit('pointerdown', $event)"
    @keydown="$emit('keydown', $event)"
    @blur="$emit('blur', $event)"
    @lostpointercapture="$emit('lostpointercapture', $event)"
    @click.stop
  >
    <svg viewBox="0 0 16 20" fill="currentColor" aria-hidden="true">
      <circle cx="5" cy="4" r="1.3" /><circle cx="11" cy="4" r="1.3" />
      <circle cx="5" cy="10" r="1.3" /><circle cx="11" cy="10" r="1.3" />
      <circle cx="5" cy="16" r="1.3" /><circle cx="11" cy="16" r="1.3" />
    </svg>
  </AppIconButton>
</template>

<style scoped>
.app-drag-handle { cursor: grab; touch-action: none; user-select: none; }
.app-drag-handle:not(:hover):not(:focus-visible):not([aria-pressed="true"]):not(:disabled) { color: var(--el-text-color-placeholder); }
.app-drag-handle[aria-pressed="true"] { cursor: grabbing; }
</style>
