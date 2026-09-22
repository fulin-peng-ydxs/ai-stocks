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
    :title="title"
    :subtitle="subtitle"
    class="app-detail-drawer"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template v-if="$slots['header-meta']" #title-suffix>
      <div class="app-detail-drawer__header-meta">
        <slot name="header-meta" />
      </div>
    </template>
    <template v-if="$slots['header-actions']" #header-actions>
      <div class="app-detail-drawer__header-actions">
        <slot name="header-actions" />
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
.app-detail-drawer__header-meta,
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
