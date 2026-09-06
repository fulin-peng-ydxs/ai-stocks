<script setup lang="ts">
import { Lock } from '@element-plus/icons-vue'
import { computed } from 'vue'
import type { ComponentState } from '@/layout/schema'

type StateKind = Exclude<ComponentState, 'ready'>
type StateSize = 'default' | 'compact' | 'tiny' | 'inline'

const props = withDefaults(defineProps<{
  state: StateKind
  title?: string
  description?: string
  size?: StateSize
  retry?: boolean
  retryText?: string
  skeletonRows?: number
  /** 无权限是 error 的语义子类型，不扩展第五种顶层状态。 */
  variant?: 'permission'
}>(), {
  size: 'default',
  retry: false,
  retryText: '重试',
  skeletonRows: 3,
})

const emit = defineEmits<{
  retry: []
}>()

const isInline = computed(() => props.size === 'inline')
const isPermission = computed(() => props.state === 'error' && props.variant === 'permission')
const emptyClass = computed(() => [
  'app-empty',
  {
    'app-empty--compact': props.size === 'compact',
    'app-empty--tiny': props.size === 'tiny',
  },
])
const resultClass = computed(() => [
  'app-state-block__result',
  {
    'app-state-block__result--compact': props.size === 'compact',
    'app-state-block__result--tiny': props.size === 'tiny',
    'app-state-block__result--inline': props.size === 'inline',
  },
])

const defaultTitle = computed(() => {
  if (props.title) return props.title
  if (isPermission.value) return '无权限查看'
  if (props.state === 'error') return '加载失败'
  if (props.state === 'loading') return '正在加载...'
  return '暂无数据'
})
const defaultDescription = computed(() => {
  if (props.description) return props.description
  if (isPermission.value) return '请联系系统管理员调整权限'
  if (props.state === 'error') return '请检查网络或稍后重试'
  return ''
})
</script>

<template>
  <div
    class="app-state-block"
    :class="[`app-state-block--${state}`, `app-state-block--${size}`, { 'app-state-block--permission': isPermission }]"
  >
    <div v-if="state === 'loading'" class="app-state-block__loading">
      <template v-if="isInline">
        <span class="app-state-block__inline-text app-caption-text">{{ defaultTitle }}</span>
      </template>
      <template v-else>
        <el-skeleton :rows="skeletonRows" animated />
        <div v-if="$slots.default || description || title" class="app-state-block__loading-text app-caption-text">
          <slot>{{ description || title || defaultTitle }}</slot>
        </div>
      </template>
    </div>

    <div v-else-if="state === 'empty' && isInline" class="app-empty-inline">
      <slot>{{ description || title || defaultTitle }}</slot>
      <div v-if="$slots.extra" class="app-state-block__actions">
        <slot name="extra" />
      </div>
    </div>

    <el-empty
      v-else-if="state === 'empty'"
      :class="emptyClass"
      :description="$slots.default || (title && description) ? '' : (description || title || defaultTitle)"
    >
      <template v-if="$slots.default || $slots.extra || (title && description)" #default>
        <slot>
          <div v-if="title && description" class="app-state-block__empty-copy">
            <strong>{{ title }}</strong>
            <span>{{ description }}</span>
          </div>
        </slot>
        <div v-if="$slots.extra" class="app-state-block__actions">
          <slot name="extra" />
        </div>
      </template>
    </el-empty>

    <div
      v-else-if="state === 'error' && isInline"
      class="app-state-block__inline-error"
      role="alert"
      aria-live="assertive"
    >
      <div class="app-state-block__inline-copy">
        <strong>{{ defaultTitle }}</strong>
        <span v-if="defaultDescription"><slot>{{ defaultDescription }}</slot></span>
      </div>
      <div v-if="retry || $slots.extra" class="app-state-block__actions">
        <slot name="extra">
          <el-button link type="primary" size="small" @click="emit('retry')">{{ retryText }}</el-button>
        </slot>
      </div>
    </div>

    <el-result
      v-else
      :icon="isPermission ? undefined : 'warning'"
      :title="defaultTitle"
      :class="resultClass"
    >
      <template v-if="isPermission" #icon>
        <el-icon class="app-state-block__permission-icon"><Lock /></el-icon>
      </template>
      <template #sub-title>
        <slot>{{ defaultDescription }}</slot>
      </template>
      <template v-if="retry || $slots.extra" #extra>
        <div class="app-state-block__actions">
          <slot name="extra">
            <el-button type="primary" @click="emit('retry')">{{ retryText }}</el-button>
          </slot>
        </div>
      </template>
    </el-result>
  </div>
</template>

<style scoped>
.app-state-block {
  width: 100%;
  min-height: 0;
}

.app-state-block--default {
  display: flex;
  min-height: 180px;
  align-items: center;
  justify-content: center;
}

.app-state-block--compact {
  min-height: 120px;
}

.app-state-block--tiny {
  min-height: 72px;
}

.app-state-block--inline {
  min-height: auto;
}

.app-state-block__loading {
  width: 100%;
  padding: 16px;
}

.app-state-block--compact .app-state-block__loading {
  padding: 12px;
}

.app-state-block--tiny .app-state-block__loading {
  padding: 8px;
}

.app-state-block--inline .app-state-block__loading {
  padding: 0;
}

.app-state-block__loading-text,
.app-state-block__inline-text {
  margin-top: 8px;
  color: var(--app-empty-text);
  font-size: var(--app-font-size-table);
  line-height: var(--app-line-height-comfy);
  text-align: center;
}

.app-state-block__inline-text {
  display: block;
  margin-top: 0;
}

.app-state-block__result {
  width: 100%;
  padding: 16px 0;
}

.app-state-block__empty-copy {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  color: var(--app-empty-text);
  font-size: var(--app-font-size-table);
  line-height: var(--app-line-height-comfy);
}

.app-state-block__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: var(--app-space-2);
}

.app-state-block--empty .app-state-block__actions {
  margin-top: var(--app-space-3);
}

.app-empty-inline .app-state-block__actions {
  margin-top: 0;
}

.app-state-block__inline-error {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  justify-content: flex-start;
  gap: var(--app-space-2);
  color: var(--app-danger-text);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-comfy);
  text-align: left;
}

.app-state-block__inline-copy {
  display: inline-flex;
  min-width: 0;
  flex-wrap: wrap;
  justify-content: flex-start;
  gap: var(--app-space-1);
  overflow-wrap: anywhere;
}

.app-state-block__inline-copy strong {
  color: var(--el-text-color-primary);
  font-weight: var(--app-font-weight-section);
}

.app-state-block__empty-copy strong {
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-section-title);
  font-weight: var(--app-font-weight-section);
}

.app-state-block__result--compact {
  padding: 8px 0;
}

.app-state-block__result--tiny {
  padding: 4px 0;
}

.app-state-block__result--inline {
  padding: 0;
}

.app-state-block__result--inline :deep(.el-result__icon) {
  display: none;
}

.app-state-block__permission-icon {
  color: var(--el-color-warning);
  font-size: var(--app-state-icon-size);
}

.app-state-block__result--inline :deep(.el-result__title p),
.app-state-block__result--inline :deep(.el-result__subtitle p) {
  display: inline;
  margin-right: 8px;
  font-size: var(--app-font-size-table);
}

.app-state-block__result--inline :deep(.el-result__extra) {
  margin-top: 0;
  display: inline-flex;
}

.app-state-block__result :deep(.el-result__title p) {
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-section-title);
  font-weight: var(--app-font-weight-section);
}

.app-state-block__result :deep(.el-result__subtitle p) {
  color: var(--app-empty-text);
  font-size: var(--app-font-size-table);
  line-height: var(--app-line-height-comfy);
}
</style>
