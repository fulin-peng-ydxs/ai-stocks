<script setup lang="ts">
import { computed, ref } from 'vue'
import AppHoverInfo from './AppHoverInfo'
import { Loading } from '@element-plus/icons-vue'

const props = withDefaults(defineProps<{
  label: string
  size?: 'xs' | 'sm' | 'md'
  variant?: 'ghost' | 'soft'
  tone?: 'default' | 'primary' | 'danger'
  disabled?: boolean
  loading?: boolean
  tooltip?: string | false
}>(), {
  size: 'md',
  variant: 'ghost',
  tone: 'default',
  disabled: false,
  loading: false,
  tooltip: undefined,
})

const button = ref<HTMLButtonElement>()
// 业务图标默认说明用途；仅明确豁免时关闭，空文案不能意外取消提示。
const tooltipContent = computed(() => props.tooltip === false ? '' : props.tooltip?.trim() || props.label.trim())

defineEmits<{
  click: [event: MouseEvent]
}>()
</script>

<template>
  <button
    ref="button"
    class="app-icon-button"
    :class="[`is-${size}`, `is-${variant}`, `is-${tone}`, { 'is-loading': loading }]"
    type="button"
    :aria-label="label"
    :aria-busy="loading ? 'true' : undefined"
    :disabled="disabled || loading"
    @click="$emit('click', $event)"
  >
    <span class="app-icon-button__glyph" aria-hidden="true">
      <Loading v-if="loading" class="app-icon-button__loading" />
      <slot v-else />
    </span>
    <slot name="badge" />
    <AppHoverInfo v-if="tooltipContent && button" :reference="button" :content="tooltipContent" :disabled="disabled || loading" />
  </button>
</template>

<style scoped>
.app-icon-button {
  --app-icon-button-size: var(--app-density-control-height, var(--app-control-height-md));
  --app-icon-button-glyph: 16px;
  position: relative;
  width: var(--app-control-row-height, var(--app-icon-button-size));
  min-width: var(--app-control-row-height, var(--app-icon-button-size));
  height: var(--app-control-row-height, var(--app-icon-button-size));
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--layout-control-radius, 6px);
  background: transparent;
  color: inherit;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  cursor: pointer;
  transition:
    background-color var(--app-motion-content) var(--app-motion-ease),
    border-color var(--app-motion-content) var(--app-motion-ease),
    color var(--app-motion-content) var(--app-motion-ease),
    box-shadow var(--app-motion-content) var(--app-motion-ease);
}
.app-icon-button.is-xs {
  --app-icon-button-size: var(--app-control-height-xs);
  --app-icon-button-glyph: 12px;
}
.app-icon-button.is-sm {
  --app-icon-button-size: var(--app-control-height-sm);
  --app-icon-button-glyph: 14px;
}
.app-icon-button__glyph {
  width: var(--app-icon-button-glyph);
  height: var(--app-icon-button-glyph);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-icon-button-glyph);
  line-height: var(--app-line-height-solid);
}
.app-icon-button__glyph :deep(svg) {
  width: 1em;
  height: 1em;
  display: block;
}
.app-icon-button__loading {
  animation: app-icon-button-spin var(--app-motion-spin) linear infinite;
}
@keyframes app-icon-button-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
