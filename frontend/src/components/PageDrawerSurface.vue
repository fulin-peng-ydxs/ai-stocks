<script setup lang="ts">
import AppScrollArea from '@/components/AppScrollArea.vue'
import AppCloseButton from './AppCloseButton.vue'
import { resetControlRowSizing } from './controlRowSizing'

resetControlRowSizing()

withDefaults(defineProps<{
  title: string
  subtitle?: string
  titleSize?: 'standard' | 'compact'
  bodyScroll?: boolean
  bodyLayout?: 'flow' | 'fill'
  closeLabel?: string
  showClose?: boolean
}>(), {
  titleSize: 'standard',
  bodyScroll: true,
  bodyLayout: 'flow',
  closeLabel: '关闭抽屉',
  showClose: true,
})

defineEmits<{
  close: []
}>()
</script>

<template>
  <section
    class="page-drawer-surface app-control-row-boundary"
    :class="{ 'is-title-compact': titleSize === 'compact' }"
  >
    <header class="page-drawer-surface__header">
      <div
        class="page-drawer-surface__heading"
      >
        <div
          class="page-drawer-surface__title"
          :class="titleSize === 'compact' ? 'app-drawer-title--compact' : 'app-drawer-title'"
        >
          <span>{{ title }}</span>
          <slot name="title-suffix" />
        </div>
        <div v-if="subtitle" class="app-drawer-subtitle">{{ subtitle }}</div>
      </div>
      <div class="page-drawer-surface__actions">
        <slot name="actions" />
        <AppCloseButton v-if="showClose" :label="closeLabel" @click="$emit('close')" />
      </div>
    </header>

    <component
      :is="bodyScroll ? AppScrollArea : 'div'"
      class="page-drawer-surface__body"
      :class="[
        `is-${bodyLayout}`,
        { 'is-scroll-disabled': !bodyScroll },
      ]"
    >
      <slot />
    </component>

    <footer v-if="$slots.footer" class="page-drawer-surface__footer">
      <slot name="footer" />
    </footer>
  </section>
</template>

<style scoped>
.page-drawer-surface {
  --app-settings-group-level-one-font-size: var(--app-font-size-section-title);
  width: 100%;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--page-settings-bg);
  border: 1px solid var(--page-settings-border);
  border-radius: var(--app-radius-overlay);
  box-shadow: 0 10px 30px var(--page-settings-shadow);
  overflow: hidden;
}
.page-drawer-surface.is-title-compact {
  --app-settings-group-level-one-font-size: var(--app-font-size-body);
}
.page-drawer-surface__header {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--app-density-overlay-padding);
  border-bottom: 1px solid var(--page-settings-divider);
}
.page-drawer-surface__heading {
  min-width: 0;
}
.page-drawer-surface__title {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-2);
  color: var(--page-settings-text);
}
.page-drawer-surface__actions {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-1);
  color: var(--page-settings-text-muted);
}
.page-drawer-surface__body {
  flex: 1 1 auto;
  min-height: 0;
  --app-scroll-padding-top: var(--app-density-overlay-padding); --app-scroll-padding-right: var(--app-density-overlay-padding); --app-scroll-padding-bottom: var(--app-density-overlay-padding); --app-scroll-padding-left: var(--app-density-overlay-padding);
}
.page-drawer-surface__body.is-scroll-disabled {
  overflow: hidden;
  padding: var(--app-density-overlay-padding);
}
.page-drawer-surface__body.is-fill {
  --app-scroll-display: flex;
  --app-scroll-direction: column;
}
.page-drawer-surface__body.is-fill.is-scroll-disabled {
  display: flex;
  flex-direction: column;
}
.page-drawer-surface__footer {
  flex: none;
  padding: var(--app-density-overlay-group-gap) var(--app-density-overlay-padding)
    var(--app-density-overlay-padding);
  border-top: 1px solid var(--page-settings-divider);
}
</style>

<style>
.app-drawer-surface-host {
  --el-drawer-bg-color: transparent;
  background: transparent;
  box-shadow: none;
}
.app-drawer-surface-host .el-drawer__header {
  display: none;
  margin: 0;
  padding: 0;
}
.app-drawer-surface-host .el-drawer__body {
  padding: var(--app-density-overlay-group-gap);
  display: flex;
  align-items: stretch;
  min-height: 0;
}
.el-overlay.app-drawer-surface-modal {
  background-color: rgba(0, 0, 0, 0.32) !important;
}
</style>
