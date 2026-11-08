<script setup lang="ts">
import AppScrollArea from '@/components/AppScrollArea.vue'
import { vKeyboardActivate } from '@/directives/keyboardActivate'
import AppHoverInfo from '@/components/AppHoverInfo'
// 走势对比队列：板块/个股/榜单共用的对比对象 chip 行。遵循按钮契约不引入原生 button：
// chip 为 role=button 容器承载激活（点击 + Enter/Space，.self 避免焦点在移除钮时连击），
// 名称继承共享紧凑选择状态，选中与悬浮分离；移除用共享 AppCloseButton。
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
  <AppScrollArea
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
        class="compare-queue-chip app-interaction-choice"
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
  </AppScrollArea>
</template>

<style scoped>
.compare-queue-rail {
  --app-scroll-display: flex;
  flex: 0 0 auto;
  --app-scroll-align: center;
  --app-scroll-gap: var(--app-space-control-gap);
  min-height: 42px;
  --app-scroll-padding-top: var(--app-space-2); --app-scroll-padding-right: var(--app-space-3); --app-scroll-padding-bottom: var(--app-space-2); --app-scroll-padding-left: var(--app-space-3);
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
  border: 1px solid var(--app-border-subtle);
  border-radius: var(--layout-control-radius);
  background: var(--el-bg-color);
  color: var(--el-text-color-regular);
  cursor: pointer;
  font: inherit;
  font-size: var(--app-font-size-caption);
}
.compare-queue-chip.error {
  border-color: var(--app-border-warning);
}

</style>
