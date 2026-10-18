<script setup lang="ts">
import { computed, inject } from 'vue'
import { PAGE_OVERLAY_TARGET } from '@/layout/pageOverlay'
import { APP_DIALOG_WIDTHS, type AppDialogSize } from './appDialogSize'
import AppScrollArea from './AppScrollArea.vue'

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  modelValue: boolean
  modalClass?: string
  size?: AppDialogSize
}>(), {
  size: 'medium',
})

const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
const model = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const pageTarget = inject(PAGE_OVERLAY_TARGET, null)
if (import.meta.env.DEV && pageTarget == null) {
  console.warn('[AppDialog] 未找到 LayoutHost 页面容器，弹窗将回退到 body。')
}
const appendTarget = computed(() => pageTarget?.value ?? 'body')
const modalClassName = computed(() => [
  'app-dialog-modal',
  props.modalClass,
].filter(Boolean).join(' '))
</script>

<template>
  <el-dialog
    v-model="model"
    v-bind="$attrs"
    :append-to="appendTarget"
    :modal-class="modalClassName"
    :width="APP_DIALOG_WIDTHS[size]"
    class="app-dialog"
  >
    <template v-if="$slots.header" #header><slot name="header" /></template>
    <AppScrollArea class="app-dialog__content"><slot /></AppScrollArea>
    <template v-if="$slots.footer" #footer><slot name="footer" /></template>
  </el-dialog>
</template>

<style>
.app-dialog {
  max-width: calc(100cqw - var(--app-space-6));
  max-height: calc(100cqh - var(--el-dialog-margin-top) - var(--app-space-6));
  display: flex;
  flex-direction: column;
}
.app-dialog.is-fullscreen { max-height: 100%; }
.app-dialog > :is(.el-dialog__header, .el-dialog__footer) { flex: none; }
.app-dialog .el-dialog__body {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.app-dialog__content { flex: 1 1 auto; min-height: 0; }
</style>
