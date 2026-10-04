<script setup lang="ts">
/** 筛选栏中独立布尔条件的紧凑开关，文案在开关两态下保持可见。 */
defineProps<{
  modelValue: boolean
  label: string
  testId?: string
  disabled?: boolean
}>()

defineEmits<{
  'update:modelValue': [value: boolean]
}>()
</script>

<template>
  <el-switch
    class="app-filter-switch"
    size="small"
    :model-value="modelValue"
    :active-text="label"
    :aria-label="label"
    :disabled="disabled"
    :data-testid="testId"
    @update:model-value="(value: boolean) => $emit('update:modelValue', value)"
  />
</template>

<style scoped>
.app-filter-switch :deep(.el-switch__label) {
  font-size: var(--app-font-size-table);
}
</style>
