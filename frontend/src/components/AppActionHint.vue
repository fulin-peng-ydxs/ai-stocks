<script setup lang="ts">
import { ref } from 'vue'
import AppHoverInfo from './AppHoverInfo'

/** 命令补充说明；禁用按钮由可聚焦的外壳承接原因，不改变按钮的执行条件。 */
defineProps<{ text?: string; disabled?: boolean; label?: string }>()
const reference = ref<HTMLSpanElement>()
</script>

<template>
  <span
    ref="reference"
    class="app-action-hint"
    :tabindex="disabled && text ? 0 : undefined"
    :aria-label="disabled && text ? label : undefined"
  >
    <slot />
    <AppHoverInfo v-if="text && reference" :reference="reference" :content="text" />
  </span>
</template>

<style scoped>
.app-action-hint {
  display: inline-flex;
  align-items: center;
  min-width: 0;
}
.app-action-hint:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
  border-radius: var(--layout-control-radius);
}
</style>
