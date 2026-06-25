<script setup lang="ts">
/**
 * 说明提示「?」——把解释性/描述性文字收进悬浮提示，避免长描述占用版面（DESIGN.md UI 规范）。
 * 仅用于"说明性"文案；操作指引、极短标签仍用明文。tooltip 贴近触发点显示，不溢出到左侧菜单。
 */
defineProps<{ text: string }>()
</script>

<template>
  <el-tooltip :content="text" placement="top" effect="dark" :show-after="80" :hide-after="0">
    <span class="help-hint" tabindex="0" role="button" aria-label="说明">?</span>
  </el-tooltip>
</template>

<style scoped>
.help-hint {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  /* 主题感知填充：白天浅灰、夜间深灰，确保 ? 在两种主题下都清晰可辨。 */
  background: var(--el-fill-color);
  border: 1px solid var(--el-border-color);
  color: var(--el-text-color-regular);
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  cursor: help;
  user-select: none;
  transition: color .15s ease, border-color .15s ease, background-color .15s ease;
}
.help-hint:hover,
.help-hint:focus-visible {
  color: #fff;
  background: var(--el-color-primary);
  border-color: var(--el-color-primary);
  outline: none;
}
</style>
