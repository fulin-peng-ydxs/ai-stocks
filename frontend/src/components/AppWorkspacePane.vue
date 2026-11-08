<script setup lang="ts">
import AppControlRow from '@/components/AppControlRow.vue'
import AppScrollArea from '@/components/AppScrollArea.vue'
import { useSlots } from 'vue'

withDefaults(defineProps<{
  title: string
  eyebrow?: string
  ariaLabel?: string
  headerVisible?: boolean
  padding?: 'none' | 'standard'
  /** 正文滚动只能由本容器或内部工作区中的一方负责。 */
  scroll?: 'delegated' | 'body'
  fill?: boolean
}>(), {
  eyebrow: '',
  ariaLabel: '',
  headerVisible: true,
  padding: 'none',
  scroll: 'delegated',
  fill: false,
})

defineSlots<{
  actions?: () => unknown
  toolbar?: () => unknown
  footer?: () => unknown
  default: () => unknown
}>()

const slots = useSlots()
</script>

<template>
  <section class="app-workspace-pane app-surface" :class="{ 'is-padded': padding === 'standard', 'is-fill': fill }" :aria-label="ariaLabel || title">
    <header
      v-if="headerVisible"
      class="app-workspace-pane__header"
    >
      <div class="app-workspace-pane__identity">
        <div v-if="eyebrow" class="app-workspace-pane__eyebrow">{{ eyebrow }}</div>
        <h3 class="app-section-title">{{ title }}</h3>
      </div>
      <AppControlRow v-if="slots.actions" class="app-workspace-pane__actions">
        <slot name="actions" />
      </AppControlRow>
    </header>
    <AppControlRow v-if="slots.toolbar" class="app-workspace-pane__toolbar">
      <slot name="toolbar" />
    </AppControlRow>
    <div class="app-workspace-pane__body">
      <AppScrollArea v-if="scroll === 'body'" class="app-workspace-pane__scroll">
        <div class="app-workspace-pane__flow"><slot /></div>
      </AppScrollArea>
      <slot v-else />
    </div>
    <AppControlRow v-if="slots.footer" justify="end" class="app-workspace-pane__footer">
      <slot name="footer" />
    </AppControlRow>
  </section>
</template>

<style scoped>
.app-workspace-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.app-workspace-pane.is-fill { flex: 1 1 auto; height: 100%; }
.app-workspace-pane__toolbar, .app-workspace-pane__footer {
  flex: none;
  padding: var(--app-space-3) var(--layout-card-padding);
}
.app-workspace-pane__toolbar { border-bottom: 1px solid var(--el-border-color-lighter); }
.app-workspace-pane__footer { border-top: 1px solid var(--el-border-color-lighter); }
.app-workspace-pane.is-padded > .app-workspace-pane__body { padding: var(--layout-card-padding); gap: var(--app-space-3); }
.app-workspace-pane__scroll { flex: 1 1 auto; min-height: 0; }
.app-workspace-pane__flow { display: grid; align-content: start; gap: var(--app-space-4); min-width: 0; }

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

</style>
