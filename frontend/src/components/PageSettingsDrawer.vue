<script setup lang="ts">
const props = defineProps<{
  modelValue: boolean
  title?: string
  dirty?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  reset: []
}>()
</script>

<template>
  <el-drawer
    :model-value="props.modelValue"
    @update:model-value="(value: boolean) => emit('update:modelValue', value)"
    direction="rtl"
    size="360px"
    class="page-settings-drawer"
  >
    <div class="ps-card">
      <header class="ps-header">
        <div class="ps-title">
          <span>{{ props.title || '页面设置' }}</span>
          <span v-if="props.dirty" class="ps-dirty-dot" />
        </div>
        <button class="ps-close" type="button" aria-label="关闭" @click="emit('update:modelValue', false)">✕</button>
      </header>

      <div class="ps-body">
        <slot />
      </div>

      <footer class="ps-footer">
        <button class="ps-reset" type="button" @click="emit('reset')">恢复默认</button>
      </footer>
    </div>
  </el-drawer>
</template>

<style scoped>
:global(.page-settings-drawer) {
  --el-drawer-bg-color: transparent;
}
:global(.page-settings-drawer .el-drawer) {
  background: transparent;
  box-shadow: none;
}
:global(.page-settings-drawer .el-drawer__header) {
  display: none;
  margin: 0;
  padding: 0;
}
:global(.page-settings-drawer .el-drawer__body) {
  padding: 14px;
  display: flex;
}
.ps-card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--page-settings-bg);
  border: 1px solid var(--page-settings-border);
  border-radius: 16px;
  box-shadow: 0 10px 30px var(--page-settings-shadow);
  overflow: hidden;
}
.ps-header {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--page-settings-divider);
}
.ps-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--page-settings-text);
}
.ps-dirty-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--page-settings-accent);
}
.ps-close {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--page-settings-text-muted);
  font-size: 14px;
  cursor: pointer;
  transition: background-color .15s ease, color .15s ease;
}
.ps-close:hover {
  background: var(--page-settings-seg-hover-bg);
  color: var(--page-settings-text);
}
.ps-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 14px 16px;
}
.ps-footer {
  flex: none;
  padding: 12px 16px 14px;
  border-top: 1px solid var(--page-settings-divider);
}
.ps-reset {
  width: 100%;
  height: 40px;
  border: 1px solid var(--page-settings-border);
  border-radius: 10px;
  background: var(--page-settings-footer-btn-bg);
  color: var(--page-settings-text);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color .15s ease;
}
.ps-reset:hover {
  background: var(--page-settings-footer-btn-hover-bg);
}
</style>
