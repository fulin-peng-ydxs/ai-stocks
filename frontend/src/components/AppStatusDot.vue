<script setup lang="ts">
import AppHoverInfo from '@/components/AppHoverInfo'

defineOptions({ inheritAttrs: false })
/** 依附主体的辅助状态；业务含义由可访问名称和悬浮说明承接。 */
withDefaults(defineProps<{
  label: string
  content?: string
  disabled?: boolean
  /** 圆形入口依附右上角，文本辅助状态保持行内。宿主须提供定位容器。 */
  placement?: 'inline' | 'top-right'
}>(), { disabled: false, placement: 'inline' })
</script>

<template>
  <AppHoverInfo :disabled="disabled || !content" :content="content" placement="top" popper-class="app-wrapping-popper">
    <span
      v-bind="$attrs"
      class="app-status-dot"
      :class="[`app-status-dot--${placement}`, { 'app-status-dot--help': content }]"
      role="img"
      :tabindex="content ? 0 : undefined"
      :aria-label="label"
    />
  </AppHoverInfo>
</template>

<style scoped>
.app-status-dot {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: var(--status-dot-size, 6px);
  height: var(--status-dot-size, 6px);
  padding: 3px 2px;
  box-sizing: content-box;
}
.app-status-dot::before {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: var(--el-color-warning);
  content: '';
}
.app-status-dot--top-right {
  position: absolute;
  top: 3px;
  right: 2px;
  width: 8px;
  height: 8px;
  padding: 0;
  border: 2px solid var(--status-dot-ring, var(--el-bg-color));
  border-radius: 50%;
}
.app-status-dot--help { cursor: help; }
.app-status-dot:focus-visible {
  border-radius: var(--el-border-radius-small);
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}
</style>
