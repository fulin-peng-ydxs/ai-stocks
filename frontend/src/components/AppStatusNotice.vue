<script setup lang="ts">
import {
  CircleCheckFilled,
  CircleCloseFilled,
  InfoFilled,
  Loading,
  WarningFilled,
} from '@element-plus/icons-vue'
import { computed } from 'vue'

type NoticeTone = 'info' | 'success' | 'warning' | 'error'
type NoticeSize = 'default' | 'compact' | 'inline'

const props = withDefaults(defineProps<{
  title: string
  description?: string
  tone?: NoticeTone
  size?: NoticeSize
  actionText?: string
  actionLoading?: boolean
  loading?: boolean
}>(), {
  description: '',
  tone: 'info',
  size: 'default',
  actionText: '',
  actionLoading: false,
  loading: false,
})

const emit = defineEmits<{
  action: []
}>()

const icon = computed(() => props.loading ? Loading : ({
  info: InfoFilled,
  success: CircleCheckFilled,
  warning: WarningFilled,
  error: CircleCloseFilled,
})[props.tone])
const role = computed(() => props.tone === 'error' ? 'alert' : 'status')
const live = computed(() => props.tone === 'error' ? 'assertive' : 'polite')
</script>

<template>
  <div
    class="app-status-notice"
    :class="[`app-status-notice--${tone}`, `app-status-notice--${size}`, { 'is-loading': loading }]"
    :role="role"
    :aria-live="live"
    :aria-busy="loading"
  >
    <el-icon class="app-status-notice__icon" aria-hidden="true"><component :is="icon" /></el-icon>
    <div class="app-status-notice__copy">
      <strong>{{ title }}</strong>
      <span v-if="description">{{ description }}</span>
      <slot />
    </div>
    <div v-if="actionText || $slots.action" class="app-status-notice__actions">
      <slot name="action">
        <el-button
          link
          type="primary"
          size="small"
          :loading="actionLoading"
          @click="emit('action')"
        >{{ actionText }}</el-button>
      </slot>
    </div>
  </div>
</template>

<style scoped>
.app-status-notice {
  --app-status-notice-color: var(--el-color-info);
  --app-status-notice-border: var(--app-border-notice-info);
  --app-status-notice-bg: var(--el-color-info-light-9);
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--app-space-2);
  padding: var(--app-space-2) var(--app-space-3);
  border: 1px solid var(--app-status-notice-border);
  border-radius: var(--layout-control-radius);
  background: var(--app-status-notice-bg);
  color: var(--el-text-color-regular);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-comfy);
}

.app-status-notice--success {
  --app-status-notice-color: var(--el-color-success);
  --app-status-notice-border: var(--app-border-notice-success);
  --app-status-notice-bg: var(--el-color-success-light-9);
}

.app-status-notice--warning {
  --app-status-notice-color: var(--app-warning-text);
  --app-status-notice-border: var(--app-border-notice-warning);
  --app-status-notice-bg: var(--el-color-warning-light-9);
}

.app-status-notice--error {
  --app-status-notice-color: var(--app-danger-text);
  --app-status-notice-border: var(--app-border-notice-danger);
  --app-status-notice-bg: var(--el-color-danger-light-9);
}

.app-status-notice--compact {
  padding: var(--app-space-2);
}

.app-status-notice--inline {
  align-items: center;
  padding: 0;
  border: 0;
  background: transparent;
}

.app-status-notice__icon {
  flex: 0 0 auto;
  color: var(--app-status-notice-color);
  font-size: var(--app-icon-size-sm);
}

.app-status-notice.is-loading .app-status-notice__icon {
  animation: app-status-notice-rotate 1s linear infinite;
}

.app-status-notice--inline .app-status-notice__icon {
  margin-top: 0;
  font-size: var(--app-font-size-body);
}

.app-status-notice__copy {
  display: flex;
  min-width: 0;
  flex: 1 1 auto;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--app-space-1);
  overflow-wrap: anywhere;
}

.app-status-notice__copy strong {
  color: var(--el-text-color-primary);
  font-weight: var(--app-font-weight-section);
}

.app-status-notice__copy span {
  color: var(--el-text-color-secondary);
}

.app-status-notice__actions {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--app-space-2);
}

@container app-viewport (max-width: 720px) {
  .app-status-notice:not(.app-status-notice--inline) {
    flex-wrap: wrap;
  }

  .app-status-notice:not(.app-status-notice--inline) .app-status-notice__actions {
    width: 100%;
    padding-left: 24px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .app-status-notice.is-loading .app-status-notice__icon {
    animation: none;
  }
}

@keyframes app-status-notice-rotate {
  to { transform: rotate(360deg); }
}
</style>
