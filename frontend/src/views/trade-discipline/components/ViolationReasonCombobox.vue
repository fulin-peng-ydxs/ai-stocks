<script lang="ts">
export interface ReasonValue {
  kind: 'builtin' | 'custom' | 'text'
  name: string
  code?: string
  id?: string
}
</script>

<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import { computed, onMounted, ref } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIconButton from '@/components/AppIconButton.vue'
import BuiltinOptionRow from '@/components/BuiltinOptionRow.vue'
import {
  deleteTradeDisciplineReason,
  listTradeDisciplineReasons,
  type ViolationReason,
} from '@/api/tradeDiscipline'

const props = defineProps<{ modelValue: ReasonValue | null; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: ReasonValue | null] }>()
const reasons = ref<ViolationReason[]>([])
const loading = ref(false)

const selectedKey = computed(() => {
  const value = props.modelValue
  if (!value) return ''
  if (value.kind === 'builtin') return `code:${value.code}`
  if (value.kind === 'custom') return `id:${value.id}`
  return value.name
})
const selectedCustomIsInactive = computed(() => props.modelValue?.kind === 'custom'
  && !reasons.value.some((item) => item.id === props.modelValue?.id))

function keyOf(reason: ViolationReason): string {
  return reason.builtin ? `code:${reason.code}` : `id:${reason.id}`
}

async function load(): Promise<void> {
  loading.value = true
  try { reasons.value = await listTradeDisciplineReasons() } catch { /* 统一请求层已反馈 */ }
  finally { loading.value = false }
}

function change(value: string): void {
  if (!value) return emit('update:modelValue', null)
  const reason = reasons.value.find((item) => keyOf(item) === value)
  if (!reason) return emit('update:modelValue', { kind: 'text', name: value.trim() })
  emit('update:modelValue', reason.builtin
    ? { kind: 'builtin', code: reason.code!, name: reason.name }
    : { kind: 'custom', id: reason.id!, name: reason.name })
}

async function remove(reason: ViolationReason): Promise<void> {
  if (!reason.id || reason.builtin || props.disabled) return
  try {
    await ElMessageBox.confirm(`删除自定义原因“${reason.name}”？`, '删除原因', {
      confirmButtonType: 'danger',
      confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning',
    })
    await deleteTradeDisciplineReason(reason.id)
    if (props.modelValue?.kind === 'custom' && props.modelValue.id === reason.id) {
      emit('update:modelValue', null)
    }
    await load()
    ElMessage.success('自定义原因已删除')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') { /* 统一请求层已反馈 */ }
  }
}

onMounted(load)
</script>

<template>
  <AppSelect
    :model-value="selectedKey"
    filterable
    allow-create
    default-first-option
    clearable
    :loading="loading"
    :disabled="disabled"
    placeholder="选择或输入一个原因"
    @update:model-value="change"
    @visible-change="(visible: boolean) => { if (visible && !reasons.length && !loading) load() }"
    popper-class="app-option-popper violation-reason-popper"
  >
    <el-option
      v-if="selectedCustomIsInactive && modelValue"
      :label="`${modelValue.name}（已停用）`"
      :value="selectedKey"
      disabled
    />
    <el-option v-for="reason in reasons" :key="keyOf(reason)" :label="reason.name" :value="keyOf(reason)">
      <BuiltinOptionRow :label="reason.name" :builtin="reason.builtin">
        <AppIconButton
          v-permission="'trade-discipline:checkin-submit'"
          label="删除自定义原因"
          tooltip="删除自定义原因"
          size="sm"
          tone="danger"
          :disabled="disabled"
          @click.stop="remove(reason)"
        ><Delete /></AppIconButton>
      </BuiltinOptionRow>
    </el-option>
  </AppSelect>
</template>

<style scoped>
.el-select { width: 100%; }
</style>
