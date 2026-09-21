<script setup lang="ts">
import type { PageDrawerSize } from './pageDrawerSize'
import AppStateBlock from './AppStateBlock.vue'
import PageDrawer from './PageDrawer.vue'

defineOptions({ inheritAttrs: false })

type DetailState = 'ready' | 'loading' | 'empty' | 'error' | 'permission'

withDefaults(defineProps<{
  modelValue: boolean
  title: string
  subtitle?: string
  size?: PageDrawerSize
  state?: DetailState
  stateTitle?: string
  stateDescription?: string
  retry?: boolean
}>(), {
  subtitle: '',
  size: 'xl',
  state: 'ready',
  stateTitle: '',
  stateDescription: '',
  retry: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  retry: []
}>()
</script>

<template>
  <PageDrawer
    v-bind="$attrs"
    :model-value="modelValue"
    :size="size"
    class="app-detail-drawer"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="app-detail-drawer__header">
        <div class="app-detail-drawer__heading">
          <h2 class="app-drawer-title">{{ title }}</h2>
          <p v-if="subtitle" class="app-drawer-subtitle">{{ subtitle }}</p>
          <slot name="header-meta" />
        </div>
        <div v-if="$slots['header-actions']" class="app-detail-drawer__header-actions">
          <slot name="header-actions" />
        </div>
      </div>
    </template>

    <AppStateBlock
      v-if="state !== 'ready'"
      :state="state === 'permission' ? 'error' : state"
      :variant="state === 'permission' ? 'permission' : undefined"
      :title="stateTitle"
      :description="stateDescription"
      :retry="retry && state === 'error'"
      @retry="emit('retry')"
    />
    <div v-else class="app-detail-drawer__body"><slot /></div>

    <template v-if="$slots.footer" #footer>
      <div class="app-detail-drawer__footer"><slot name="footer" /></div>
    </template>
  </PageDrawer>
</template>

<style scoped>
.app-detail-drawer__header {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-4);
}
.app-detail-drawer__heading { min-width: 0; }
.app-detail-drawer__header-actions,
.app-detail-drawer__footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--app-space-2);
}
.app-detail-drawer__body {
  display: grid;
  min-width: 0;
  gap: var(--app-space-4);
}
</style>
