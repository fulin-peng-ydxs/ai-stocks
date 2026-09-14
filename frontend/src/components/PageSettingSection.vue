<script setup lang="ts">
/**
 * 设置抽屉内的子分组（页面设置抽屉三段「布局 / 组件设置 / 业务选项」内部的次级分组）。
 * 默认可折叠：点标题收起/展开本组，并与其他设置分组共用递归父控子协议。
 * 无标题时不渲染头、不可折叠。
 */
import { computed, ref } from 'vue'
import { Expand, Fold } from '@element-plus/icons-vue'
import { useSettingsFoldTree } from '../composables/useSettingsFoldTree'
import AppIconButton from './AppIconButton.vue'
import HelpHint from './HelpHint.vue'

const props = withDefaults(
  defineProps<{ title?: string; desc?: string; collapsible?: boolean }>(),
  { collapsible: true },
)
const open = ref(true)
const openState = computed(() => open.value)
const foldable = () => props.collapsible && !!props.title
function setOpen(value: boolean): void {
  open.value = value
}
function toggle() {
  if (foldable()) setOpen(!open.value)
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
    class="page-setting-section"
    data-settings-fold-node
    :data-settings-group-title="title"
    :data-settings-group-open="openState"
  >
    <header
      v-if="title || desc"
      class="pss-head"
      :class="{ 'is-foldable': foldable(), 'is-collapsed': foldable() && !open }"
      :role="foldable() ? 'button' : undefined"
      :tabindex="foldable() ? 0 : undefined"
      @click="toggle"
      @keydown.enter.prevent="toggle"
      @keydown.space.prevent="toggle"
    >
      <span v-if="title" class="pss-title app-caption-text">{{ title }}</span>
      <HelpHint v-if="desc" :text="desc" @click.stop />
      <span v-if="hasChildGroups" class="pss-actions" @click.stop @keydown.stop>
        <AppIconButton :label="childToggleLabel" size="xs" @click="toggleChildGroups">
          <el-icon><Expand v-if="allChildGroupsClosed" /><Fold v-else /></el-icon>
        </AppIconButton>
      </span>
    </header>
    <div v-show="open || !foldable()" class="pss-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.page-setting-section + .page-setting-section {
  margin-top: var(--app-density-overlay-group-gap);
  padding-top: var(--app-density-overlay-group-gap);
  border-top: 1px solid var(--page-settings-section-border);
}
.pss-head {
  display: flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  margin-bottom: var(--app-density-overlay-group-gap);
}
.pss-actions {
  display: inline-flex;
  align-items: center;
  margin-left: auto;
}
.pss-head.is-foldable {
  cursor: pointer;
  user-select: none;
}
/* 子级折叠块不用箭头：标题加虚下划线提示"可点折叠"（与第一层卡片的箭头区分层级）。 */
.pss-head.is-foldable .pss-title {
  text-decoration: underline dotted;
  text-underline-offset: 3px;
  text-decoration-color: var(--page-settings-text-muted);
}
.pss-head.is-foldable:hover .pss-title {
  color: var(--page-settings-text);
  text-decoration-color: var(--page-settings-accent);
}
.pss-title {
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-section);
  letter-spacing: .04em;
  text-transform: uppercase;
  color: var(--page-settings-text-subtle);
}
.pss-body {
  display: flex;
  flex-direction: column;
  gap: var(--app-density-form-gap);
}
</style>
