<script setup lang="ts">
import { computed, inject } from 'vue'
import { PAGE_OVERLAY_TARGET } from '@/layout/pageOverlay'
import {
  PAGE_DRAWER_WIDTHS,
  type PageDrawerSize,
} from './pageDrawerSize'

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  modelValue: boolean
  modalClass?: string
  size?: PageDrawerSize
  titleSize?: 'standard' | 'compact'
}>(), {
  size: 'md',
  titleSize: 'standard',
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()
const model = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const pageTarget = inject(PAGE_OVERLAY_TARGET, null)
if (import.meta.env.DEV && pageTarget == null) {
  console.warn('[PageDrawer] 未找到 LayoutHost 页面容器，抽屉将回退到 body。')
}
// 真实页面由 LayoutHost 提供目标；body 回退仅兼容组件预览与把 LayoutHost 替换为测试桩的场景。
const appendTarget = computed(() => pageTarget?.value ?? 'body')
const modalClassName = computed(() => [
  'page-drawer-modal',
  `page-drawer-modal--title-${props.titleSize}`,
  props.size === 'full' ? 'page-drawer-modal--full' : '',
  props.modalClass,
].filter(Boolean).join(' '))
const drawerWidth = computed(() => PAGE_DRAWER_WIDTHS[props.size])
</script>

<template>
  <el-drawer
    v-model="model"
    v-bind="$attrs"
    :append-to="appendTarget"
    :modal-class="modalClassName"
    :size="drawerWidth"
  >
    <template v-if="$slots.header" #header>
      <slot name="header" />
    </template>
    <slot />
    <template v-if="$slots.footer" #footer>
      <slot name="footer" />
    </template>
  </el-drawer>
</template>

<style>
/* PageDrawer teleport 到 LayoutHost 根节点；absolute 让遮罩严格服从页面边界，而非视口。 */
.el-overlay.page-drawer-modal {
  position: absolute;
}
.el-overlay.page-drawer-modal .el-drawer__title {
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-drawer-title);
  line-height: var(--app-line-height-drawer-title);
  font-weight: var(--app-font-weight-section);
}
.el-overlay.page-drawer-modal--title-compact .el-drawer__title {
  font-size: var(--app-font-size-section-title);
  line-height: var(--app-line-height-section-title);
}
.el-overlay.page-drawer-modal--full .el-drawer {
  width: 100% !important;
  max-width: none;
}
</style>
