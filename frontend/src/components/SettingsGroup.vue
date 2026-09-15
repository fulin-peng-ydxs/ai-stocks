<script setup lang="ts">
/**
 * 通用可折叠分组（设置抽屉的固有结构单元）。层级由卡片、缩进和结构线表达，
 * 标题字号按语义角色稳定分档，不随嵌套深度持续缩小。
 */
import { computed, ref, watch } from 'vue'
import { Expand, Fold } from '@element-plus/icons-vue'
import { useSettingsFoldTree } from '../composables/useSettingsFoldTree'
import AppIconButton from './AppIconButton.vue'
import HelpHint from './HelpHint.vue'

const props = withDefaults(
  defineProps<{
    title?: string
    hint?: string
    badge?: string
    level?: number
    collapsible?: boolean
    defaultOpen?: boolean
    modelValue?: boolean
  }>(),
  // modelValue 显式给 undefined 默认值：避免 Vue 对未受控的 Boolean prop 强制转成 false
  // （否则 isOpen() 的 `modelValue ?? localOpen` 会被 false 短路，导致非受控子组永远折叠且点不开）。
  { level: 1, collapsible: true, defaultOpen: true, modelValue: undefined },
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
const foldable = () => props.collapsible && !!props.title
const openState = computed(() => props.modelValue ?? localOpen.value)

function setOpen(value: boolean): void {
  if (openState.value === value) return
  if (props.modelValue === undefined) localOpen.value = value
  emit('update:modelValue', value)
}

function toggle(): void {
  if (foldable()) setOpen(!openState.value)
}

const {
  allChildGroupsClosed,
  hasChildGroups,
  setRootElement,
  toggleChildGroups,
} = useSettingsFoldTree(openState, setOpen)
const childToggleLabel = computed(() => (
  `${props.title || '当前分组'}：${allChildGroupsClosed.value ? '展开' : '收起'}下级分组`
))

</script>

<template>
  <section
    :ref="setRootElement"
    class="sg"
    :class="[
      `sg-l${level}`,
      {
        'sg-nested': level > 1,
        'sg-open': openState || !foldable(),
      },
    ]"
    data-settings-fold-node
    :data-settings-group-title="title"
    :data-settings-group-open="openState"
  >
    <div
      v-if="title || badge"
      class="sg-head"
      :class="{ 'sg-foldable': foldable(), 'sg-top': level === 1 }"
      :role="foldable() ? 'button' : undefined"
      :tabindex="foldable() ? 0 : undefined"
      @click="toggle"
      @keydown.enter.prevent="toggle"
      @keydown.space.prevent="toggle"
    >
      <span v-if="foldable()" class="sg-caret" :class="{ open: openState }" aria-hidden="true">▸</span>
      <span v-if="title" class="sg-title">{{ title }}</span>
      <HelpHint v-if="hint" :text="hint" @click.stop />
      <span v-if="badge || hasChildGroups || $slots.actions" class="sg-tail" @click.stop @keydown.stop>
        <span v-if="badge" class="sg-badge">{{ badge }}</span>
        <span v-if="hasChildGroups || $slots.actions" class="sg-actions">
          <AppIconButton
            v-if="hasChildGroups"
            class="sg-toggle-children"
            :label="childToggleLabel"
            size="xs"
            @click="toggleChildGroups"
          >
            <el-icon><Expand v-if="allChildGroupsClosed" /><Fold v-else /></el-icon>
          </AppIconButton>
          <slot name="actions" />
        </span>
      </span>
    </div>
    <div v-show="openState || !foldable()" class="sg-body"><slot /></div>
  </section>
</template>

<style scoped>
/* ── 第一层：卡片 + 箭头 ───────────────────────────── */
.sg-l1 {
  border: 1px solid var(--page-settings-section-border);
  border-radius: 12px;
  background: var(--page-settings-section-bg);
  overflow: hidden;
}
.sg-l1 + .sg-l1 {
  margin-top: var(--app-density-overlay-group-gap);
}
.sg-l1 > .sg-head {
  padding: var(--app-density-overlay-group-gap) var(--app-density-overlay-padding);
}
.sg-l1 > .sg-head:hover {
  background: var(--page-settings-seg-hover-bg);
}
.sg-l1 > .sg-head .sg-title {
  font-size: var(--app-font-size-section-title);
  font-weight: var(--app-font-weight-strong);
  color: var(--page-settings-text);
}
.sg-l1 > .sg-body {
  padding: 2px var(--app-density-overlay-padding) var(--app-density-overlay-padding);
}

/* ── 第二层及更深：用树状缩进和结构线表达归属，不继续压缩字号 ── */
.sg-nested + .sg-nested {
  margin-top: var(--app-density-overlay-group-gap);
  padding-top: var(--app-density-overlay-group-gap);
  border-top: 1px solid var(--page-settings-section-border);
}
.sg-nested > .sg-head {
  min-height: var(--app-control-height-sm);
  padding: 2px var(--app-space-1);
  border-radius: var(--layout-control-radius);
}
.sg-nested > .sg-head:hover {
  background: var(--page-settings-seg-hover-bg);
}
.sg-nested > .sg-head .sg-title {
  font-size: var(--app-font-size-body);
  font-weight: var(--app-font-weight-section);
  color: var(--page-settings-text);
}
.sg-l3 > .sg-head .sg-title {
  font-size: var(--app-font-size-body);
  font-weight: var(--app-font-weight-medium);
  color: var(--page-settings-text-subtle);
}
.sg-nested > .sg-body {
  margin-left: 9px;
  padding-left: var(--app-space-3);
  border-left: 1px solid var(--page-settings-section-border);
}

/* ── 通用 ───────────────────────────────────────── */
.sg-head {
  display: flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  margin-bottom: 0;
}
.sg-nested.sg-open > .sg-head {
  margin-bottom: var(--app-density-overlay-group-gap);
}
.sg-head.sg-foldable {
  cursor: pointer;
  user-select: none;
}
.sg-caret {
  width: 12px;
  flex: none;
  display: inline-flex;
  justify-content: center;
  font-size: var(--app-font-size-micro);
  color: var(--page-settings-text-muted);
  transition: transform .15s ease;
}
.sg-caret.open {
  transform: rotate(90deg);
}
.sg-badge {
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-solid);
  padding: 3px 8px;
  border-radius: 999px;
  color: var(--page-settings-text-subtle);
  border: 1px solid var(--page-settings-border);
  background: var(--page-settings-bg);
}
.sg-tail {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-2);
}
.sg-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-2);
}
.sg-body {
  display: flex;
  flex-direction: column;
  gap: var(--app-density-form-gap);
}
</style>
