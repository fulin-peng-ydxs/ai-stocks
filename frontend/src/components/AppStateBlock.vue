<script setup lang="ts">
import { Lock } from '@element-plus/icons-vue'
import { computed } from 'vue'

type StateKind = 'loading' | 'empty' | 'error' | 'permission'
type StateSize = 'default' | 'compact' | 'tiny' | 'inline'

const props = withDefaults(defineProps<{
  state: StateKind
  title?: string
  description?: string
  size?: StateSize
  retry?: boolean
  retryText?: string
  skeletonRows?: number
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
  if (props.state === 'permission') return '无权限查看'
  if (props.state === 'error') return '加载失败'
  if (props.state === 'loading') return '正在加载...'
  return '暂无数据'
})
const defaultDescription = computed(() => {
  if (props.description) return props.description
  if (props.state === 'permission') return '请联系系统管理员调整权限'
  if (props.state === 'error') return '请检查网络或稍后重试'
  return ''
})
</script>

<template>
  <div class="app-state-block" :class="[`app-state-block--${state}`, `app-state-block--${size}`]">
    <div v-if="state === 'loading'" class="app-state-block__loading">
      <template v-if="isInline">
        <span class="app-state-block__inline-text">{{ defaultTitle }}</span>
      </template>
      <template v-else>
        <el-skeleton :rows="skeletonRows" animated />
        <div v-if="$slots.default || description || title" class="app-state-block__loading-text">
          <slot>{{ description || title || defaultTitle }}</slot>
        </div>
      </template>
    </div>

    <div v-else-if="state === 'empty' && isInline" class="app-empty-inline">
      <slot>{{ description || title || defaultTitle }}</slot>
    </div>

    <el-empty
      v-else-if="state === 'empty'"
      :class="emptyClass"
      :description="$slots.default ? '' : (description || title || defaultTitle)"
    >
      <template v-if="$slots.default || $slots.extra" #default>
        <slot />
        <slot name="extra" />
      </template>
    </el-empty>

    <el-result
      v-else
      :icon="state === 'permission' ? undefined : 'warning'"
      :title="defaultTitle"
      :class="resultClass"
    >
      <template v-if="state === 'permission'" #icon>
        <el-icon class="app-state-block__permission-icon"><Lock /></el-icon>
      </template>
      <template #sub-title>
        <slot>{{ defaultDescription }}</slot>
      </template>
      <template v-if="retry || $slots.extra" #extra>
        <slot name="extra">
          <el-button type="primary" @click="emit('retry')">{{ retryText }}</el-button>
        </slot>
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
  font-size: 13px;
  line-height: 1.5;
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
  font-size: 64px;
}

.app-state-block__result--inline :deep(.el-result__title p),
.app-state-block__result--inline :deep(.el-result__subtitle p) {
  display: inline;
  margin-right: 8px;
  font-size: 13px;
}

.app-state-block__result--inline :deep(.el-result__extra) {
  margin-top: 0;
  display: inline-flex;
}

.app-state-block__result :deep(.el-result__title p) {
  color: var(--el-text-color-primary);
  font-size: 15px;
  font-weight: 600;
}

.app-state-block__result :deep(.el-result__subtitle p) {
  color: var(--app-empty-text);
  font-size: 13px;
  line-height: 1.5;
}
</style>
