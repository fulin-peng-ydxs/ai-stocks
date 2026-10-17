<script setup lang="ts">
import { ElCollapseTransition } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'

// 只统一 disclosure 的结构、可访问性和视觉边界，业务状态与命令由消费方注入。
const props = withDefaults(defineProps<{
  panelId: string
  indexLabel?: string
  title: string
  toggleLabel: string
  meta?: string | null
  preview?: string | null
  previewFallback?: string
  expanded: boolean
  muted?: boolean
  toggleTestId?: string
  editorTestId?: string
  /** 紧凑只读清单沿用同一 disclosure，避免消费方覆写折叠结构和动效。 */
  variant?: 'card' | 'compact'
  collapsible?: boolean
}>(), {
  indexLabel: '',
  meta: null,
  preview: null,
  previewFallback: '暂无摘要',
  muted: false,
  toggleTestId: 'summary-card-toggle',
  editorTestId: 'summary-card-editor',
  variant: 'card',
  collapsible: true,
})

const emit = defineEmits<{ toggle: [] }>()
function toggle() {
  if (props.collapsible) emit('toggle')
}
</script>

<template>
  <article
    class="app-summary-disclosure-card"
    :class="{
      'is-expanded': expanded && collapsible, 'is-muted': muted,
      'is-compact': variant === 'compact', 'is-static': !collapsible,
    }"
  >
    <div class="app-summary-disclosure-card__bar">
      <component
        :is="collapsible ? 'button' : 'div'"
        :type="collapsible ? 'button' : undefined"
        class="app-summary-disclosure-card__summary"
        :class="{ 'has-leading': $slots.leading || indexLabel }"
        data-overflow-tooltip-disabled
        :aria-expanded="collapsible ? expanded : undefined"
        :aria-controls="collapsible ? panelId : undefined"
        :aria-label="collapsible ? toggleLabel : undefined"
        :data-testid="toggleTestId"
        @click="toggle"
      >
        <span v-if="$slots.leading || indexLabel" class="app-summary-disclosure-card__leading">
          <slot name="leading"><span class="app-summary-disclosure-card__index">{{ indexLabel }}</span></slot>
        </span>
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
        <ArrowDown v-if="collapsible" class="app-summary-disclosure-card__chevron" aria-hidden="true" />
      </component>

      <div v-if="$slots.tools" class="app-summary-disclosure-card__tools">
        <slot name="tools" />
      </div>
    </div>

    <ElCollapseTransition>
      <div
        v-if="expanded && collapsible"
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
  border: 1px solid var(--app-border-default);
  border-radius: var(--layout-card-radius);
  background: var(--app-surface-container);
  overflow: hidden;
}
.app-summary-disclosure-card.is-expanded {
  border-color: var(--app-border-selected);
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
  grid-template-columns: minmax(0, 1fr) 16px;
  align-items: center;
  gap: var(--app-space-2);
  padding: var(--app-space-2) var(--app-space-3);
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.app-summary-disclosure-card__summary.has-leading { grid-template-columns: 28px minmax(0, 1fr) 16px; }
.app-summary-disclosure-card__leading { display: inline-flex; align-items: center; }
.app-summary-disclosure-card__summary:hover {
  background: var(--app-surface-hover);
}
.app-summary-disclosure-card__summary:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px var(--el-color-primary-light-5);
}
.app-summary-disclosure-card__index {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: var(--app-surface-control);
  color: var(--el-text-color-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-font-size-caption);
  font-variant-numeric: tabular-nums;
}
.is-expanded .app-summary-disclosure-card__index {
  background: var(--app-surface-selected);
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
  background: var(--app-surface-container);
}
.app-summary-disclosure-card__editor :deep(.el-form-item:last-child) { margin-bottom: 0; }

/* 报告型清单只保留行分隔；所有状态共用相同对齐、留白和正文表面。 */
.app-summary-disclosure-card.is-compact {
  border: 0;
  border-bottom: 1px solid var(--el-border-color-extra-light);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
.is-compact .app-summary-disclosure-card__bar { min-height: var(--app-density-control-height); }
.is-compact .app-summary-disclosure-card__summary { padding: var(--app-space-2) 0; }
.is-compact .app-summary-disclosure-card__summary.has-leading { grid-template-columns: auto minmax(0, 1fr) 16px; }
.is-compact .app-summary-disclosure-card__copy { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--app-space-1) var(--app-space-2); }
.is-compact .app-summary-disclosure-card__title-row { flex: 0 1 auto; flex-wrap: wrap; }
.is-compact .app-summary-disclosure-card__title-row strong { white-space: normal; overflow-wrap: anywhere; }
.is-compact .app-summary-disclosure-card__preview { flex: 1 1 120px; margin: 0; white-space: normal; overflow-wrap: anywhere; }
.is-compact .app-summary-disclosure-card__editor { padding: var(--app-space-2) 0 var(--app-space-3); border-top: 0; }
.is-static .app-summary-disclosure-card__summary { cursor: default; }
.is-static .app-summary-disclosure-card__summary:hover { background: transparent; }

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
