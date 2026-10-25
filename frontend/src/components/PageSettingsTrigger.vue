<script setup lang="ts">
import { Setting } from '@element-plus/icons-vue'
import AppIconButton from './AppIconButton.vue'

defineProps<{ dirty?: boolean }>()
defineEmits<{ click: [] }>()
</script>

<template>
  <AppIconButton
    class="page-settings-trigger"
    data-testid="page-settings-trigger"
    label="页面设置"
    @click="$emit('click')"
  >
    <el-icon><Setting /></el-icon>
    <span v-if="dirty" class="dot" />
  </AppIconButton>
</template>

<style scoped>
.dot {
  position: absolute;
  top: 5px;
  right: 5px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--page-settings-accent);
  box-shadow: 0 0 0 2px var(--page-settings-dot-ring);
}
</style>
