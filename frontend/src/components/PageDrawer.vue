<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import type { DrawerInstance } from 'element-plus'
import { PAGE_OVERLAY_TARGET } from '@/layout/pageOverlay'
import {
  PAGE_DRAWER_WIDTHS,
  type PageDrawerSize,
} from './pageDrawerSize'
import PageDrawerSurface from './PageDrawerSurface.vue'
import { resetControlRowSizing } from './controlRowSizing'

defineOptions({ inheritAttrs: false })
resetControlRowSizing()

const props = withDefaults(defineProps<{
  modelValue: boolean
  modalClass?: string
  size?: PageDrawerSize
  title: string
  subtitle?: string
  titleSize?: 'standard' | 'compact'
  bodyScroll?: boolean
  bodyLayout?: 'flow' | 'fill'
  boundary?: 'page' | 'app'
  closeLabel?: string
  showClose?: boolean
}>(), {
  size: 'md',
  titleSize: 'standard',
  bodyScroll: true,
  bodyLayout: 'flow',
  boundary: 'page',
  subtitle: '',
  closeLabel: '',
  showClose: true,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()
const model = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const pageTarget = inject(PAGE_OVERLAY_TARGET, null)
if (import.meta.env.DEV && props.boundary === 'page' && pageTarget == null) {
  console.warn('[PageDrawer] 未找到 LayoutHost 页面容器，抽屉将回退到 body。')
}
// 真实页面由 LayoutHost 提供目标；body 回退仅兼容组件预览与把 LayoutHost 替换为测试桩的场景。
const appendTarget = computed(() => (
  props.boundary === 'app' ? 'body' : (pageTarget?.value ?? 'body')
))
const modalClassName = computed(() => [
  'page-drawer-modal',
  props.boundary === 'app' ? 'page-drawer-modal--app' : '',
  `page-drawer-modal--title-${props.titleSize}`,
  'page-drawer-modal--surface',
  'app-drawer-surface-modal',
  props.size === 'full' ? 'page-drawer-modal--full' : '',
  props.modalClass,
].filter(Boolean).join(' '))
const drawer = ref<DrawerInstance>()
// 自定义头部与遮罩/Escape 共同经过组件库 before-close，不能直接改 v-model 绕过拦截。
function requestClose() { drawer.value?.handleClose() }
const drawerWidth = computed(() => PAGE_DRAWER_WIDTHS[props.size])
const resolvedCloseLabel = computed(() => props.closeLabel || `关闭${props.title}`)
</script>

<template>
  <el-drawer
    ref="drawer"
    v-model="model"
    v-bind="$attrs"
    :aria-label="title"
    :show-close="false"
    :append-to="appendTarget"
    class="page-drawer--surface app-drawer-surface-host app-control-row-boundary"
    :modal-class="modalClassName"
    :size="drawerWidth"
  >
    <PageDrawerSurface
      :title="title"
      :subtitle="subtitle"
      :title-size="titleSize"
      :body-scroll="bodyScroll"
      :body-layout="bodyLayout"
      :close-label="resolvedCloseLabel"
      :show-close="showClose"
      @close="requestClose"
    >
      <template v-if="$slots['title-suffix']" #title-suffix>
        <slot name="title-suffix" />
      </template>
      <template v-if="$slots['header-actions']" #actions>
        <slot name="header-actions" />
      </template>
      <slot />
      <template v-if="$slots.footer" #footer>
        <slot name="footer" />
      </template>
    </PageDrawerSurface>
  </el-drawer>
</template>

<style>
/* PageDrawer teleport 到 LayoutHost 根节点；absolute 让遮罩严格服从页面边界，而非视口。 */
.el-overlay.page-drawer-modal {
  position: absolute;
}
.el-overlay.page-drawer-modal--app {
  position: fixed;
}
.el-overlay.page-drawer-modal .el-drawer {
  max-width: 100%;
}
.el-overlay.page-drawer-modal--full .el-drawer {
  width: 100% !important;
  max-width: none;
}
</style>
