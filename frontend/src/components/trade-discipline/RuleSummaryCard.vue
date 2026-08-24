<script setup lang="ts">
import { ArrowDown } from '@element-plus/icons-vue'

const props = withDefaults(defineProps<{
  panelId: string
  indexLabel: string
  title: string
  meta: string
  content?: string | null
  enabled: boolean
  expanded: boolean
  editable: boolean
}>(), {
  content: null,
})

const emit = defineEmits<{
  toggle: []
  'update:enabled': [value: boolean]
}>()
</script>

<template>
  <article class="rule-summary-card" :class="{ 'is-expanded': expanded, 'is-disabled': !enabled }">
    <div class="rule-summary-card__bar">
      <button
        type="button"
        class="rule-summary-card__summary"
        :aria-expanded="expanded"
        :aria-controls="panelId"
        :aria-label="`${expanded ? '收起' : '展开'}规则“${title}”`"
        data-testid="rule-card-toggle"
        @click="emit('toggle')"
      >
        <span class="rule-summary-card__index">{{ indexLabel }}</span>
        <span class="rule-summary-card__copy">
          <span class="rule-summary-card__title-row">
            <strong>{{ title }}</strong>
            <span>{{ meta }}</span>
          </span>
          <span class="rule-summary-card__preview">{{ content?.trim() || '尚未填写规则内容' }}</span>
        </span>
        <ArrowDown class="rule-summary-card__chevron" aria-hidden="true" />
      </button>

      <div class="rule-summary-card__tools">
        <el-switch
          :model-value="enabled"
          :disabled="!editable"
          :aria-label="`${enabled ? '停用' : '启用'}规则“${title}”`"
          @update:model-value="emit('update:enabled', $event)"
        />
        <div v-if="editable" class="rule-summary-card__actions">
          <slot name="actions" />
        </div>
      </div>
    </div>

    <div v-if="expanded" :id="panelId" class="rule-summary-card__editor" data-testid="rule-card-editor">
      <slot />
    </div>
  </article>
</template>

<style scoped>
.rule-summary-card {
  min-width: 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 7px;
  background: var(--el-bg-color);
  overflow: hidden;
}
.rule-summary-card.is-expanded {
  border-color: var(--el-color-primary-light-5);
  box-shadow: inset 3px 0 0 var(--el-color-primary);
}
.rule-summary-card__bar {
  min-height: 68px;
  display: flex;
  align-items: stretch;
}
.rule-summary-card__summary {
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
.rule-summary-card__summary:hover {
  background: var(--el-fill-color-extra-light);
}
.rule-summary-card__summary:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px var(--el-color-primary-light-5);
}
.rule-summary-card__index {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-font-size-caption);
  font-variant-numeric: tabular-nums;
}
.is-expanded .rule-summary-card__index {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.rule-summary-card__copy { min-width: 0; }
.rule-summary-card__title-row {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: var(--app-space-2);
}
.rule-summary-card__title-row strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-table);
}
.rule-summary-card__title-row span {
  flex: none;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.rule-summary-card__preview {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.is-disabled .rule-summary-card__title-row strong,
.is-disabled .rule-summary-card__preview { color: var(--el-text-color-placeholder); }
.rule-summary-card__chevron {
  width: 14px;
  color: var(--el-text-color-placeholder);
  transition: transform 0.15s ease;
}
.is-expanded .rule-summary-card__chevron { transform: rotate(180deg); }
.rule-summary-card__tools {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--app-space-1);
  padding: 0 var(--app-space-2);
  border-left: 1px solid var(--el-border-color-extra-light);
}
.rule-summary-card__actions { display: flex; align-items: center; gap: var(--app-space-1); }
.rule-summary-card__editor {
  padding: var(--app-space-3);
  border-top: 1px solid var(--el-border-color-extra-light);
  background: var(--el-fill-color-extra-light);
}
.rule-summary-card__editor :deep(.el-form-item:last-child) { margin-bottom: 0; }

@media (max-width: 760px) {
  .rule-summary-card__bar { flex-direction: column; }
  .rule-summary-card__tools {
    min-height: 36px;
    justify-content: space-between;
    border-top: 1px solid var(--el-border-color-extra-light);
    border-left: 0;
  }
}
</style>
