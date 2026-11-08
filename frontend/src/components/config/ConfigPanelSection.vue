<script setup lang="ts">
import { vKeyboardActivate } from '@/directives/keyboardActivate'
import { ref, watch } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'

const props = withDefaults(
  defineProps<{
    title?: string
    description?: string
    summary?: string
    badge?: string
    level?: 1 | 2
    collapsible?: boolean
    defaultOpen?: boolean
    showDescription?: boolean
    modelValue?: boolean
  }>(),
  { level: 1, collapsible: true, defaultOpen: true, showDescription: true, modelValue: undefined },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const localOpen = ref(props.defaultOpen)

watch(
  () => props.defaultOpen,
  (value) => {
    if (props.modelValue === undefined) localOpen.value = value
  },
)

function foldable(): boolean {
  return props.collapsible && !!props.title
}

function isOpen(): boolean {
  if (!foldable()) return true
  return props.modelValue ?? localOpen.value
}

function toggle() {
  if (!foldable()) return
  const next = !isOpen()
  if (props.modelValue === undefined) localOpen.value = next
  emit('update:modelValue', next)
}
</script>

<template>
  <section class="config-panel-section" :class="[`is-level-${level}`, { 'is-closed': !isOpen(), 'has-summary': !!summary, 'app-surface': level === 1 }]">
    <div
      v-if="title || badge"
      class="config-panel-section__head app-section-header"
      :class="{ 'is-foldable': foldable(), 'app-interaction-disclosure': foldable(), 'app-section-header--plain': level === 2 }"
      :role="foldable() ? 'button' : undefined"
      :tabindex="foldable() ? 0 : undefined"
      :aria-expanded="foldable() ? isOpen() : undefined"
      @click="toggle"
      v-keyboard-activate
    >
      <el-icon v-if="foldable()" class="config-panel-section__caret">
        <ArrowDown />
      </el-icon>
      <div class="config-panel-section__copy">
        <span v-if="title" class="config-panel-section__title">{{ title }}</span>
        <span v-if="summary" class="config-panel-section__summary">{{ summary }}</span>
        <span
          v-if="level === 1 && showDescription && description"
          class="config-panel-section__description"
        >
          {{ description }}
        </span>
      </div>
      <span v-if="badge" class="config-panel-section__badge">{{ badge }}</span>
    </div>
    <div v-show="isOpen() || !foldable()" class="config-panel-section__body">
      <p
        v-if="level === 2 && showDescription && description"
        class="config-panel-section__body-description"
      >
        {{ description }}
      </p>
      <slot />
    </div>
  </section>
</template>

<style scoped>
.config-panel-section {
  min-width: 0;
}

.is-level-1 {
  overflow: hidden;
}

.is-level-1 + .is-level-1 {
  margin-top: 12px;
}

.is-level-1 > .config-panel-section__head {
  min-height: 48px;
  padding: 11px 14px;
}

.is-level-1 > .config-panel-section__body {
  padding: 16px 14px 18px;
}

.is-level-2 {
  padding: 0;
}

.is-level-2 + .is-level-2 {
  margin-top: var(--app-space-3);
}

.is-level-2 > .config-panel-section__head {
  align-items: center;
  gap: var(--app-space-2);
  min-height: 24px;
  padding: 0 0 8px;
}

.is-level-2 > .config-panel-section__head::after {
  content: "";
  flex: 1 1 auto;
  min-width: 72px;
  height: 1px;
}

.is-level-2 > .config-panel-section__body {
  padding: 0;
}

.is-level-2 > .config-panel-section__head + .config-panel-section__body {
  padding-left: 24px;
}

.config-panel-section__body-description {
  margin: 0 0 12px;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}

.config-panel-section__head {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  min-width: 0;
}

.config-panel-section__head.is-foldable {
  cursor: pointer;
  user-select: none;
}


.config-panel-section__caret {
  flex: none;
  color: var(--el-text-color-secondary);
  transition: transform .16s ease;
}

.is-closed > .config-panel-section__head .config-panel-section__caret {
  transform: rotate(-90deg);
}

.config-panel-section__title {
  display: block;
  min-width: 0;
  color: var(--el-text-color-primary);
  font-weight: var(--app-font-weight-section);
  line-height: var(--app-line-height-compact);
}

.config-panel-section__copy {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: var(--app-space-1);
  min-width: 0;
}

.config-panel-section__description {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}

.config-panel-section.has-summary > .config-panel-section__head .config-panel-section__copy {
  flex-direction: row;
  flex-wrap: wrap;
  align-items: baseline;
  column-gap: var(--app-space-3);
}
.config-panel-section__summary {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
  overflow-wrap: anywhere;
}

.is-level-1 > .config-panel-section__head .config-panel-section__title {
  font-size: var(--app-font-size-section-title);
}

.is-level-2 > .config-panel-section__head .config-panel-section__title {
  font-size: var(--app-font-size-body);
}

.is-level-2 > .config-panel-section__head .config-panel-section__copy {
  flex: 0 1 auto;
  max-width: calc(100% - 96px);
}

.config-panel-section__badge {
  margin-left: auto;
  flex: none;
  padding: 2px 8px;
  border: 1px solid var(--app-border-subtle);
  border-radius: 999px;
  background: var(--el-fill-color-blank);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}

.is-level-2 > .config-panel-section__head .config-panel-section__badge {
  display: none;
}

@container app-viewport (max-width: 720px) {
  .is-level-2 > .config-panel-section__head::after {
    min-width: 28px;
  }

  .is-level-2 > .config-panel-section__head .config-panel-section__copy {
    max-width: calc(100% - 56px);
  }
}
</style>
