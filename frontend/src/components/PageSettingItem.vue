<script setup lang="ts">
import HelpHint from './HelpHint.vue'
import { computed, onBeforeUnmount, onMounted, onUpdated, ref, shallowRef } from 'vue'
import { SETTING_ITEM_LAYOUT_GROUP, measureSettingItemInlineWidth, type SettingItemLayoutElement, type SettingItemLayoutGroup } from '@/composables/settingItemLayout'

const props = withDefaults(defineProps<{
  label?: string
  hint?: string
  layout?: 'stacked' | 'inline'
}>(), {
  label: '',
  hint: '',
  layout: 'stacked',
})

const root = ref<HTMLElement>()
const switchOnly = ref(false)
const cannotFit = ref(false)
const group = shallowRef<SettingItemLayoutGroup>()
let unregister: (() => void) | undefined
const effectiveLayout = computed(() => props.layout === 'inline'
  && !cannotFit.value && (switchOnly.value || !group.value?.stacked.value) ? 'inline' : 'stacked')
let observer: ResizeObserver | undefined
let frame: number | undefined

function measure() {
  const element = root.value
  if (!element) return
  const control = element.querySelector<HTMLElement>(':scope > .psi-control')
  const switches = control?.querySelectorAll('[role="switch"], input[type="checkbox"]')
  // 一个真实开关可同时含 role=switch 和内部 checkbox；其它输入仍参与兄弟项对齐。
  switchOnly.value = !!switches?.length && !control?.querySelector(
    'input:not([type="checkbox"]):not([type="hidden"]), textarea, [role="combobox"], [role="spinbutton"]',
  ) && (control?.querySelectorAll('[role="switch"]').length === 1 || switches.length === 1)
  if (props.layout !== 'inline' || element.clientWidth === 0) return
  const style = getComputedStyle(element)
  const available = element.clientWidth - parseFloat(style.paddingLeft || '0') - parseFloat(style.paddingRight || '0')
  cannotFit.value = measureSettingItemInlineWidth(element) > available + 1
}
function scheduleMeasure() {
  if (frame !== undefined) return
  frame = requestAnimationFrame(() => { frame = undefined; measure() })
}
onMounted(() => {
  const parent = root.value?.parentElement?.closest<SettingItemLayoutElement>('[data-settings-fold-node]')
  group.value = parent?.[SETTING_ITEM_LAYOUT_GROUP]
  unregister = group.value?.register({ requested: () => props.layout, switchOnly, cannotFit })
  measure()
  if (typeof ResizeObserver !== 'undefined' && root.value) {
    observer = new ResizeObserver(scheduleMeasure)
    observer.observe(root.value)
    for (const child of root.value.children) observer.observe(child)
  }
})
onUpdated(scheduleMeasure)
onBeforeUnmount(() => {
  observer?.disconnect()
  if (frame !== undefined) cancelAnimationFrame(frame)
  unregister?.()
})
</script>

<template>
  <div ref="root" class="page-setting-item" :class="`is-${effectiveLayout}`">
    <div v-if="label || $slots.label || hint || $slots.actions" class="psi-label-row">
      <span v-if="label || $slots.label" class="psi-label">
        <slot name="label">{{ label }}</slot>
      </span>
      <HelpHint v-if="hint" :text="hint" />
      <span v-if="$slots.actions" class="psi-actions"><slot name="actions" /></span>
    </div>
    <div class="psi-control"><slot /></div>
    <div v-if="$slots.help" class="psi-help"><slot name="help" /></div>
  </div>
</template>

<style scoped>
.page-setting-item {
  display: flex;
  min-width: 0;
  max-width: 100%;
  gap: var(--app-space-2);
}
.page-setting-item.is-stacked {
  flex-direction: column;
  align-items: stretch;
}
.page-setting-item.is-inline {
  min-height: var(--app-density-control-height);
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-density-control-gap);
}
.psi-label-row {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--app-space-control-gap);
}
.psi-label {
  min-width: 0;
  font-size: var(--app-font-size-table);
  line-height: var(--app-line-height-table);
  font-weight: var(--app-font-weight-medium);
  color: var(--page-settings-text-subtle);
}
.psi-actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-2);
}
.psi-control {
  min-width: 0;
  max-width: 100%;
}
.is-stacked > .psi-control {
  width: 100%;
}
.is-inline > .psi-control {
  flex: none;
  display: inline-flex;
  align-items: center;
}
.is-inline > .psi-label-row > .psi-label { white-space: nowrap; }
.psi-help {
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
  color: var(--page-settings-text-muted);
}
</style>
