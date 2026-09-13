<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Star, StarFilled } from '@element-plus/icons-vue'
import AppIconButton from '@/components/AppIconButton.vue'
import { addMembers, removeMembers } from '@/api/stockGroup'

const props = withDefaults(defineProps<{
  groupId: string
  code: string
  name?: string | null
  active?: boolean
  defaultDate?: string
}>(), {
  name: null,
  active: false,
  defaultDate: '',
})

const emit = defineEmits<{
  changed: [active: boolean]
}>()

const loading = ref(false)

async function toggle(): Promise<void> {
  if (!props.groupId || !props.code || loading.value) return
  loading.value = true
  try {
    if (props.active) await removeMembers(props.groupId, [props.code])
    else await addMembers(props.groupId, [props.code], props.defaultDate || undefined)
    const next = !props.active
    emit('changed', next)
    ElMessage.success(`${next ? '已加入' : '已移出'}自选：${props.name || props.code}`)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AppIconButton
    v-permission="'stock-group:member-update'"
    class="stock-group-favorite-button"
    :class="{ 'stock-group-favorite-button--active': active }"
    :label="`${active ? '移出' : '加入'}自选分组：${name || code}`"
    :loading="loading"
    size="xs"
    :native-title="false"
    @click.stop="toggle"
  >
    <el-icon><StarFilled v-if="active" /><Star v-else /></el-icon>
  </AppIconButton>
</template>

<style scoped>
.stock-group-favorite-button {
  color: var(--el-text-color-placeholder);
}
.stock-group-favorite-button--active {
  color: var(--el-color-primary);
}
</style>
