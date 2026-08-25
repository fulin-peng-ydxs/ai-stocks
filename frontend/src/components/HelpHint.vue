<script setup lang="ts">
/**
 * 说明提示「?」——承载可作为一个纯文本块理解的解释性文案，避免说明占用常驻版面。
 * 需要标题、分段、列表、示例或多要点结构时改用 HelpTip + HelpTipItem；操作指引和极短标签仍用明文。
 */
defineProps<{ text: string }>()
</script>

<template>
  <el-tooltip
    :content="text"
    :trigger="['hover', 'focus']"
    placement="top"
    effect="dark"
    :show-after="80"
    :hide-after="0"
  >
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
  font-size: var(--app-font-size-micro);
  font-weight: var(--app-font-weight-section);
  line-height: var(--app-line-height-solid);
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
