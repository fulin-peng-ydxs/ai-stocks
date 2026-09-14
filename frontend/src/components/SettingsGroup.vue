<script setup lang="ts">
/**
 * 通用可折叠分组（设置抽屉的固有结构单元）——支持任意嵌套层级，标题按 level 成比例递减。
 * 折叠提示规则（DESIGN.md §11/§12）：仅第一层（level=1，卡片）用箭头 chevron；
 * 更深层级用虚下划线提示可点。层数不写死，递归自适应。
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
    :class="[`sg-l${level}`]"
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
      <span v-if="foldable() && level === 1" class="sg-caret" :class="{ open: openState }" aria-hidden="true">▸</span>
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

/* ── 第二层及更深：无卡片、标题虚下划线提示可点，字号递减 ───── */
.sg-l2 + .sg-l2,
.sg-l3 + .sg-l3,
.sg-l2 + .sg-l3,
.sg-l3 + .sg-l2 {
  margin-top: var(--app-density-overlay-group-gap);
  padding-top: var(--app-density-overlay-group-gap);
  border-top: 1px solid var(--page-settings-section-border);
}
/* 深层标题作为"高于内容"的小标题：字号随层级递减但不低于正文(13px)，颜色加强以锚定其下控件。 */
.sg-l2 > .sg-head .sg-title {
  font-size: var(--app-font-size-body);
  font-weight: var(--app-font-weight-section);
  color: var(--page-settings-text);
}
.sg-l3 > .sg-head .sg-title {
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  letter-spacing: .04em;
  text-transform: uppercase;
  color: var(--page-settings-text-subtle);
}
.sg-l2 > .sg-body,
.sg-l3 > .sg-body {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}

/* ── 通用 ───────────────────────────────────────── */
.sg-head {
  display: flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  margin-bottom: 0;
}
.sg-l2 > .sg-head,
.sg-l3 > .sg-head {
  margin-bottom: var(--app-density-overlay-group-gap);
}
.sg-head.sg-foldable {
  cursor: pointer;
  user-select: none;
}
/* 非第一层折叠块：标题虚下划线（不用箭头） */
.sg-foldable:not(.sg-top) .sg-title {
  text-decoration: underline dotted;
  text-underline-offset: 3px;
  text-decoration-color: var(--page-settings-text-muted);
}
.sg-foldable:not(.sg-top):hover .sg-title {
  color: var(--page-settings-text);
  text-decoration-color: var(--page-settings-accent);
}
.sg-caret {
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
