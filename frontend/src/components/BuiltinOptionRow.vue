<script setup lang="ts">
defineProps<{
  label: string
  builtin: boolean
}>()
</script>

<template>
  <span class="builtin-option-row">
    <span class="builtin-option-row__label">{{ label }}</span>
    <span v-if="builtin" class="builtin-option-label">内置</span>
    <span v-else class="builtin-option-row__action"><slot /></span>
  </span>
</template>

<style scoped>
.builtin-option-row {
  width: 100%;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}
.builtin-option-row__label {
  min-width: 0;
  overflow: hidden;
  flex: 1 1 auto;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.builtin-option-label,
.builtin-option-row__action {
  margin-left: auto;
  flex: none;
}
.builtin-option-label {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.builtin-option-row__action {
  display: inline-flex;
  align-items: center;
}
</style>
