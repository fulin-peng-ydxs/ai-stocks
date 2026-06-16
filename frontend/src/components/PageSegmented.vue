<script setup lang="ts">
type OptionValue = string | number | boolean

defineProps<{
  modelValue: OptionValue
  options: { label: string; value: OptionValue }[]
}>()

defineEmits<{
  'update:modelValue': [value: OptionValue]
}>()
</script>

<template>
  <div class="page-segmented">
    <button
      v-for="option in options"
      :key="String(option.value)"
      type="button"
      class="seg-btn"
      :class="{ active: option.value === modelValue }"
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
  gap: 6px;
}
.seg-btn {
  min-height: 38px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: var(--page-settings-seg-bg);
  color: var(--page-settings-text-subtle);
  font-size: 13px;
  font-weight: 600;
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
