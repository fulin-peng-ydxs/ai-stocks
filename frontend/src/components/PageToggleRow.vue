<script setup lang="ts">
import PageSettingItem from '@/components/PageSettingItem.vue'
withDefaults(defineProps<{
  label: string
  modelValue: boolean
  tip?: string
  size?: 'md' | 'sm'
  testId?: string
  disabled?: boolean
}>(), { size: 'md' })

defineEmits<{
  'update:modelValue': [value: boolean]
}>()
</script>

<template>
  <PageSettingItem
    class="page-toggle-row"
    :class="`is-${size}`"
    :data-testid="testId"
    :label="label"
    :hint="tip"
    layout="inline"
  >
    <el-switch
      :model-value="modelValue"
      class="ptr-switch"
      :data-testid="testId ? `${testId}-switch` : undefined"
      inline-prompt
      :disabled="disabled"
      :active-action-icon="undefined"
      @update:model-value="(value: boolean) => $emit('update:modelValue', value)"
    />
  </PageSettingItem>
</template>

<style scoped>
.page-toggle-row.is-sm {
  min-height: var(--app-control-height-sm);
}
:global(.ptr-switch.el-switch) {
  --el-switch-off-color: var(--page-settings-switch-off);
  --el-switch-on-color: var(--page-settings-accent);
}
</style>
