<script setup lang="ts">
import AppHoverInfo from '@/components/AppHoverInfo'
// 通用帮助气泡：默认插槽只承载 HelpTipItem，确保问题项、注意项和分行结构一致。
defineProps<{ title?: string; width?: number; testId?: string }>()
</script>

<template>
  <AppHoverInfo
    kind="popover"
    :title="title"
    :width="width ?? 360"
    placement="bottom-start"
  >
    <template #reference>
      <span
        class="help-icon"
        tabindex="0"
        role="button"
        aria-label="说明"
        :data-testid="testId"
      >?</span>
    </template>
    <div class="help-body">
      <slot />
    </div>
  </AppHoverInfo>
</template>

<style scoped>
.help-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  align-self: center;
  width: 16px;
  height: 16px;
  margin-left: 6px;
  border-radius: 50%;
  background: var(--app-section-bg);
  border: 1px solid var(--el-border-color);
  color: var(--el-text-color-regular);
  font-size: var(--app-font-size-micro);
  font-weight: var(--app-font-weight-strong);
  cursor: help;
  vertical-align: middle;
  transition: color .15s ease, border-color .15s ease, background-color .15s ease;
}
.help-icon:hover,
.help-icon:focus-visible {
  color: var(--el-color-white);
  background: var(--el-color-primary);
  border-color: var(--el-color-primary);
}
.help-body {
  display: flex;
  flex-direction: column;
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-longform);
  color: var(--el-text-color-regular);
}
.help-icon:focus-visible { outline: var(--app-focus-ring); outline-offset: 2px; }
</style>
