<script setup lang="ts">
/**
 * 设置抽屉内的子分组（页面设置抽屉三段「布局 / 组件设置 / 业务选项」内部的次级分组）。
 * 默认可折叠：点标题收起/展开本组，与外层三段的折叠形成两级。无标题时不渲染头、不可折叠。
 */
import { ref } from 'vue'
import HelpHint from './HelpHint.vue'

const props = withDefaults(
  defineProps<{ title?: string; desc?: string; collapsible?: boolean }>(),
  { collapsible: true },
)
const open = ref(true)
const foldable = () => props.collapsible && !!props.title
function toggle() {
  if (foldable()) open.value = !open.value
}
</script>

<template>
  <section class="page-setting-section">
    <header
      v-if="title || desc"
      class="pss-head"
      :class="{ 'is-foldable': foldable(), 'is-collapsed': foldable() && !open }"
      @click="toggle"
    >
      <span v-if="title" class="pss-title">{{ title }}</span>
      <HelpHint v-if="desc" :text="desc" @click.stop />
    </header>
    <div v-show="open || !foldable()" class="pss-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.page-setting-section + .page-setting-section {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--page-settings-section-border);
}
.pss-head {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 10px;
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
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .04em;
  text-transform: uppercase;
  color: var(--page-settings-text-subtle);
}
.pss-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>
