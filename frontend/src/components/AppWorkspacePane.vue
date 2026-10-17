<script setup lang="ts">
import { useSlots } from 'vue'

withDefaults(defineProps<{
  title: string
  eyebrow?: string
  ariaLabel?: string
  headerVisible?: boolean
}>(), {
  eyebrow: '',
  ariaLabel: '',
  headerVisible: true,
})

defineSlots<{
  actions?: () => unknown
  default: () => unknown
}>()

const slots = useSlots()
</script>

<template>
  <section class="app-workspace-pane" :aria-label="ariaLabel || title">
    <header
      v-if="headerVisible"
      class="app-workspace-pane__header"
    >
      <div class="app-workspace-pane__identity">
        <div v-if="eyebrow" class="app-workspace-pane__eyebrow">{{ eyebrow }}</div>
        <h3 class="app-section-title">{{ title }}</h3>
      </div>
      <div v-if="slots.actions" class="app-workspace-pane__actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="app-workspace-pane__body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.app-workspace-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
}

.app-workspace-pane__header {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  min-height: 64px;
  padding: var(--app-space-3) var(--app-space-4);
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}

.app-workspace-pane__identity {
  min-width: 0;
}

.app-workspace-pane__identity h3 {
  overflow: hidden;
  margin: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-workspace-pane__eyebrow {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
  font-weight: var(--app-font-weight-strong);
  letter-spacing: 0.14em;
}

.app-workspace-pane__actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--app-space-2);
  min-width: 0;
}

.app-workspace-pane__body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.app-workspace-pane__body > :deep(.app-stock-chart-frame) {
  border: 0;
  border-radius: 0;
}
</style>
