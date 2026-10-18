<script setup lang="ts">
import { computed, nextTick, onUpdated, ref, watch, type CSSProperties, type Component } from 'vue'
import { ElScrollbar, type ScrollbarInstance } from 'element-plus'
import { registerScrollbarGeometry } from './scroll/installScrollbarPolicy'

defineOptions({ inheritAttrs: false })
withDefaults(defineProps<{
  as?: string | Component
  axis?: 'x' | 'y' | 'both'
  contentStyle?: CSSProperties
  ariaLabel?: string
}>(), { axis: 'both', as: 'div' })

const scrollbar = ref<ScrollbarInstance>()
const viewport = computed(() => scrollbar.value?.wrapRef)
watch(scrollbar, (instance, _, onCleanup) => {
  if (instance) onCleanup(registerScrollbarGeometry(instance.$el, () => instance.update()))
}, { flush: 'post' })
onUpdated(() => { void nextTick(() => scrollbar.value?.update()) })
defineExpose({
  viewport,
  scrollTo: (options: ScrollToOptions) => scrollbar.value?.scrollTo(options),
  setScrollTop: (value: number) => scrollbar.value?.setScrollTop(value),
  setScrollLeft: (value: number) => scrollbar.value?.setScrollLeft(value),
  update: () => scrollbar.value?.update(),
})
</script>

<template>
  <component
    :is="typeof as === 'string' && ['pre', 'dl'].includes(as) ? 'div' : as"
    v-bind="$attrs"
    class="app-scroll-area"
    :aria-label="ariaLabel"
  >
    <ElScrollbar
      ref="scrollbar"
      class="app-scroll-area__renderer"
      :class="`app-scroll-area--${axis}`"
      view-class="app-scroll-area__content"
      :tag="typeof as === 'string' && ['pre', 'dl'].includes(as) ? as : 'div'"
      :view-style="contentStyle"
      :aria-label="ariaLabel"
      :always="true"
      :min-size="20"
    ><slot /></ElScrollbar>
    <template v-for="name in Object.keys($slots).filter(name => name !== 'default')" #[name]="slotProps">
      <slot :name="name" v-bind="slotProps || {}" />
    </template>
  </component>
</template>

<style scoped>
.app-scroll-area {
  /* 每个实例重置内容布局变量，禁止从外层滚动区继承。 */
  --app-scroll-display: block;
  --app-scroll-direction: row;
  --app-scroll-wrap: nowrap;
  --app-scroll-gap: normal;
  --app-scroll-align: normal;
  --app-scroll-justify: normal;
  --app-scroll-columns: none;
  --app-scroll-rows: none;
  --app-scroll-padding-top: 0;
  --app-scroll-padding-right: 0;
  --app-scroll-padding-bottom: 0;
  --app-scroll-padding-left: 0;
  --app-scroll-align-content: normal;
  --app-scroll-position: static;
  height: auto;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: clip;
}
.app-scroll-area > .app-scroll-area__renderer {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  width: 100%;
  height: auto;
  min-height: 0;
  max-height: inherit;
}
.app-scroll-area :deep(> .app-scroll-area__renderer > .el-scrollbar__wrap) {
  flex: 1 1 auto;
  height: auto;
  min-height: 0;
  max-height: inherit;
}
.app-scroll-area--x :deep(> .el-scrollbar__wrap) { overflow-y: hidden; }
.app-scroll-area--y :deep(> .el-scrollbar__wrap) { overflow-x: hidden; }
.app-scroll-area :deep(> .app-scroll-area__renderer > .el-scrollbar__wrap > .app-scroll-area__content) {
  box-sizing: border-box;
  margin: 0;
  position: var(--app-scroll-position);
  min-height: 100%;
  height: 100%;
  display: var(--app-scroll-display);
  flex-direction: var(--app-scroll-direction);
  flex-wrap: var(--app-scroll-wrap);
  gap: var(--app-scroll-gap);
  align-items: var(--app-scroll-align);
  align-content: var(--app-scroll-align-content);
  justify-content: var(--app-scroll-justify);
  grid-template-columns: var(--app-scroll-columns);
  grid-template-rows: var(--app-scroll-rows);
  padding: var(--app-scroll-padding-top) var(--app-scroll-padding-right)
    var(--app-scroll-padding-bottom) var(--app-scroll-padding-left);
}
</style>
