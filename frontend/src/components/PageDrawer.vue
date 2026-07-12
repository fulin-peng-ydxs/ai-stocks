<script setup lang="ts">
import { computed, inject } from 'vue'
import { PAGE_OVERLAY_TARGET } from '@/layout/pageOverlay'

defineOptions({ inheritAttrs: false })

const props = defineProps<{
  modelValue: boolean
  modalClass?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const pageTarget = inject(PAGE_OVERLAY_TARGET, null)
if (import.meta.env.DEV && pageTarget == null) {
  console.warn('[PageDrawer] 未找到 LayoutHost 页面容器，抽屉将回退到 body。')
}
// 真实页面由 LayoutHost 提供目标；body 回退仅兼容组件预览与把 LayoutHost 替换为测试桩的场景。
const appendTarget = computed(() => pageTarget?.value ?? 'body')
const modalClassName = computed(() => ['page-drawer-modal', props.modalClass].filter(Boolean).join(' '))
</script>

<template>
  <el-drawer
    v-bind="$attrs"
    :model-value="props.modelValue"
    :append-to="appendTarget"
    :modal-class="modalClassName"
    @update:model-value="(value: boolean) => emit('update:modelValue', value)"
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
</style>
