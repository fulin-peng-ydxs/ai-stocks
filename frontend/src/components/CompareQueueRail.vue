<script setup lang="ts">
import { vKeyboardActivate } from '@/directives/keyboardActivate'
import AppHoverInfo from '@/components/AppHoverInfo'
// 走势对比队列：板块/个股/榜单共用的对比对象 chip 行。遵循按钮契约不引入原生 button：
// chip 为 role=button 容器承载激活（点击 + Enter/Space，.self 避免焦点在移除钮时连击），
// 名称为纯 span 继承 chip 颜色（激活/悬浮随主色变蓝），移除用共享 AppCloseButton。
import AppCloseButton from '@/components/AppCloseButton.vue'

export interface CompareQueueItem {
  key: string
  label: string
  active?: boolean
  error?: string | null
}

withDefaults(defineProps<{
  items: CompareQueueItem[]
  label?: string
  hint?: string
  max?: number
  ariaLabel?: string
  testIdPrefix?: string
}>(), {
  label: '对比队列',
  hint: '',
  max: 6,
  ariaLabel: '当前对比项',
  testIdPrefix: '',
})

const emit = defineEmits<{
  activate: [key: string]
  remove: [key: string]
}>()
</script>

<template>
  <div
    class="compare-queue-rail"
    :aria-label="ariaLabel"
    :data-testid="testIdPrefix ? `${testIdPrefix}-compare-rail` : undefined"
  >
    <span class="compare-queue-label">{{ label }}</span>
    <AppHoverInfo
      v-for="item in items"
      :key="item.key"
      :content="item.error || undefined"
      :disabled="!(item.error || undefined)"
    >
      <div
        class="compare-queue-chip"
        :class="{ active: item.active, error: Boolean(item.error) }"
        role="button"
        tabindex="0"
        :aria-pressed="item.active ? 'true' : 'false'"
        :data-testid="testIdPrefix ? `${testIdPrefix}-compare-${item.key}` : undefined"
        @click="emit('activate', item.key)"
        v-keyboard-activate
      >
        <span class="compare-queue-name">{{ item.label }}</span>
        <AppCloseButton
          v-if="!item.active || items.length > 1"
          class="compare-queue-remove"
          :label="`移除对比：${item.label}`"
          :data-testid="testIdPrefix ? `${testIdPrefix}-remove-${item.key}` : undefined"
          size="inline"
          @click.stop="emit('remove', item.key)"
        />
      </div>
    </AppHoverInfo>
    <span v-if="hint && items.length < max" class="compare-queue-hint">{{ hint }}</span>
  </div>
</template>

<style scoped>
.compare-queue-rail {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--app-space-control-gap);
  min-height: 42px;
  padding: var(--app-space-2) var(--app-space-3);
  overflow-x: auto;
  border-bottom: 1px solid var(--el-border-color-lighter);
  white-space: nowrap;
}
.compare-queue-label,
.compare-queue-hint {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
}
.compare-queue-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-1);
  height: var(--app-control-height-sm);
  padding: 0 var(--app-space-2);
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-control-radius);
  background: var(--el-bg-color);
  color: var(--el-text-color-regular);
  cursor: pointer;
  font: inherit;
  font-size: var(--app-font-size-caption);
}
.compare-queue-chip:hover,
.compare-queue-chip.active,
.compare-queue-chip:focus-visible {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.compare-queue-chip:focus-visible {
  outline: var(--app-focus-ring);
  outline-offset: 1px;
}
.compare-queue-chip.error {
  border-color: var(--el-color-warning);
}

</style>
