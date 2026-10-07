<script setup lang="ts">
import { ElCollapseTransition } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'

// 只统一 disclosure 的结构、可访问性和视觉边界，业务状态与命令由消费方注入。
withDefaults(defineProps<{
  panelId: string
  indexLabel: string
  title: string
  toggleLabel: string
  meta?: string | null
  preview?: string | null
  previewFallback?: string
  expanded: boolean
  muted?: boolean
  toggleTestId?: string
  editorTestId?: string
}>(), {
  meta: null,
  preview: null,
  previewFallback: '暂无摘要',
  muted: false,
  toggleTestId: 'summary-card-toggle',
  editorTestId: 'summary-card-editor',
})

const emit = defineEmits<{ toggle: [] }>()
</script>

<template>
  <article
    class="app-summary-disclosure-card"
    :class="{ 'is-expanded': expanded, 'is-muted': muted }"
  >
    <div class="app-summary-disclosure-card__bar">
      <button
        type="button"
        class="app-summary-disclosure-card__summary"
        data-overflow-tooltip-disabled
        :aria-expanded="expanded"
        :aria-controls="panelId"
        :aria-label="toggleLabel"
        :data-testid="toggleTestId"
        @click="emit('toggle')"
      >
        <span class="app-summary-disclosure-card__index">{{ indexLabel }}</span>
        <span class="app-summary-disclosure-card__copy">
          <span class="app-summary-disclosure-card__title-row">
            <strong>{{ title }}</strong>
            <span v-if="meta" class="app-summary-disclosure-card__meta">{{ meta }}</span>
            <slot name="status" />
          </span>
          <span class="app-summary-disclosure-card__preview">
            {{ preview?.trim() || previewFallback }}
          </span>
        </span>
        <ArrowDown class="app-summary-disclosure-card__chevron" aria-hidden="true" />
      </button>

      <div v-if="$slots.tools" class="app-summary-disclosure-card__tools">
        <slot name="tools" />
      </div>
    </div>

    <ElCollapseTransition>
      <div
        v-if="expanded"
        :id="panelId"
        class="app-summary-disclosure-card__editor app-motion-collapse"
        :data-testid="editorTestId"
      >
        <slot />
      </div>
    </ElCollapseTransition>
  </article>
</template>

<style scoped>
.app-summary-disclosure-card {
  min-width: 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
  overflow: hidden;
}
.app-summary-disclosure-card.is-expanded {
  border-color: color-mix(in srgb, var(--el-color-primary) 62%, var(--el-border-color));
  box-shadow: inset 3px 0 0 var(--el-color-primary);
}
.app-summary-disclosure-card__bar {
  min-height: 68px;
  display: flex;
  align-items: stretch;
}
.app-summary-disclosure-card__summary {
  min-width: 0;
  flex: 1 1 auto;
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 16px;
  align-items: center;
  gap: var(--app-space-2);
  padding: var(--app-space-2) var(--app-space-3);
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.app-summary-disclosure-card__summary:hover {
  background: color-mix(in srgb, var(--el-fill-color-light) 58%, transparent);
}
.app-summary-disclosure-card__summary:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px var(--el-color-primary-light-5);
}
.app-summary-disclosure-card__index {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--app-section-bg) 68%, var(--el-bg-color));
  color: var(--el-text-color-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-font-size-caption);
  font-variant-numeric: tabular-nums;
}
.is-expanded .app-summary-disclosure-card__index {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 76%, var(--el-bg-color));
  color: var(--el-color-primary);
}
.app-summary-disclosure-card__copy { min-width: 0; }
.app-summary-disclosure-card__title-row {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: var(--app-space-2);
}
.app-summary-disclosure-card__title-row strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-table);
}
.app-summary-disclosure-card__meta {
  flex: none;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.app-summary-disclosure-card__preview {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.is-muted .app-summary-disclosure-card__title-row strong,
.is-muted .app-summary-disclosure-card__preview { color: var(--el-text-color-placeholder); }
.app-summary-disclosure-card__chevron {
  width: 14px;
  color: var(--el-text-color-placeholder);
  transition: transform var(--app-motion-collapse) var(--app-motion-ease);
}
.is-expanded .app-summary-disclosure-card__chevron { transform: rotate(180deg); }
.app-summary-disclosure-card__tools {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--app-space-1);
  padding: 0 var(--app-space-2);
  border-left: 1px solid var(--el-border-color-extra-light);
}
.app-summary-disclosure-card__editor {
  padding: var(--app-space-3);
  border-top: 1px solid var(--el-border-color-extra-light);
  background: var(--el-bg-color);
}
.app-summary-disclosure-card__editor :deep(.el-form-item:last-child) { margin-bottom: 0; }

@media (prefers-reduced-motion: reduce) {
  .app-summary-disclosure-card__chevron { transition: none; }
}

@container app-viewport (max-width: 760px) {
  .app-summary-disclosure-card__bar { flex-direction: column; }
  .app-summary-disclosure-card__tools {
    min-height: 36px;
    justify-content: space-between;
    border-top: 1px solid var(--el-border-color-extra-light);
    border-left: 0;
  }
}
</style>
