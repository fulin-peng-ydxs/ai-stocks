<script setup lang="ts">
import { Close } from '@element-plus/icons-vue'
import AppIconButton from './AppIconButton.vue'

/** 只承载关闭/移除临时界面的呈现；是否允许离开由所属容器决定。 */
withDefaults(defineProps<{
  label: string
  size?: 'default' | 'compact' | 'inline'
  disabled?: boolean
  loading?: boolean
}>(), {
  size: 'default',
  disabled: false,
  loading: false,
})
defineEmits<{ click: [event: MouseEvent] }>()
</script>

<template>
  <AppIconButton
    class="app-close-control"
    :data-close-size="size"
    :label="label"
    :tooltip="false"
    :size="size === 'default' ? 'sm' : 'xs'"
    :disabled="disabled"
    :loading="loading"
    @click.stop="$emit('click', $event)"
    @keydown.enter.stop
    @keydown.space.stop
  >
    <Close />
  </AppIconButton>
</template>
