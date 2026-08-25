<script setup lang="ts">
/**
 * HelpTip 的结构化说明项：question 展示传入的问题文本，warning 固定展示“注意”，二者只能选一个。
 * 冒号、警告色和正文列表排版均由组件统一承载，调用方不重复拼接。
 */
defineProps<{ question?: string; warning?: true }>()
</script>

<template>
  <div class="help-tip-item" :class="{ 'is-warning': warning }">
    <span class="help-tip-label">{{ warning ? '注意' : question }}：</span>
    <div class="help-tip-content"><slot /></div>
  </div>
</template>

<style scoped>
.help-tip-item {
  display: flex;
  flex-direction: column;
  row-gap: var(--app-space-1);
  color: var(--el-text-color-regular);
}

.help-tip-item + .help-tip-item {
  margin-top: var(--app-space-2);
}

.help-tip-label {
  font-weight: var(--app-font-weight-section);
}

.help-tip-item.is-warning {
  color: var(--app-warning-text);
}

.help-tip-content {
  min-width: 0;
}

.help-tip-content :deep(> :first-child) {
  margin-top: 0;
}

.help-tip-content :deep(> :last-child) {
  margin-bottom: 0;
}

.help-tip-content :deep(ul) {
  display: flex;
  flex-direction: column;
  row-gap: var(--app-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.help-tip-content :deep(li) {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  column-gap: var(--app-space-1);
}

.help-tip-content :deep(li::before) {
  content: '.';
}
</style>
