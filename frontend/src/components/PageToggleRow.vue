<script setup lang="ts">
defineProps<{
  label: string
  modelValue: boolean
  tip?: string
}>()

defineEmits<{
  'update:modelValue': [value: boolean]
}>()
</script>

<template>
  <div class="page-toggle-row">
    <div class="ptr-left">
      <span class="ptr-label">{{ label }}</span>
      <el-tooltip v-if="tip" :content="tip" placement="top">
        <span class="ptr-tip">i</span>
      </el-tooltip>
    </div>
    <el-switch
      :model-value="modelValue"
      class="ptr-switch"
      inline-prompt
      :active-action-icon="undefined"
      @update:model-value="(value: boolean) => $emit('update:modelValue', value)"
    />
  </div>
</template>

<style scoped>
.page-toggle-row {
  min-height: 40px;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.ptr-left {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.ptr-label {
  font-size: 14px;
  color: var(--page-settings-text);
}
.ptr-tip {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--page-settings-text-muted);
  border: 1px solid var(--page-settings-tip-border);
}
:global(.ptr-switch.el-switch) {
  --el-switch-off-color: var(--page-settings-switch-off);
  --el-switch-on-color: var(--page-settings-accent);
}
</style>
