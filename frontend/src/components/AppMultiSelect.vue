<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import AppSelect from '@/components/AppSelect.vue'
import { getErrorMessage } from '@/utils/error'
import { createLatestRequestGuard } from '@/utils/latestRequestGuard'

export interface AppMultiSelectOption {
  value: string
  label: string
}

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  modelValue: string[]
  options?: readonly AppMultiSelectOption[]
  /** 远程候选来源；传入后由基础组件管理搜索状态和响应竞态。 */
  loadOptions?: (keyword: string) => Promise<AppMultiSelectOption[]>
  /** 批量精确校验并返回有效候选；省略时按已有候选或 allowCreate 处理。 */
  resolveValues?: (values: string[]) => Promise<AppMultiSelectOption[]>
  normalizeValue?: (value: string) => string
  /** 默认按逗号或换行拆分，领域代码可显式增加空白分隔。 */
  pasteSeparator?: RegExp
  allowCreate?: boolean
  disabled?: boolean
  loading?: boolean
  /** 业务上下文变化时清理候选和未完成请求，保留调用方传入的选值。 */
  contextKey?: string
  noDataText?: string
  loadErrorMessage?: string
  validationErrorMessage?: string
  rejectedMessage?: (values: string[]) => string
}>(), {
  options: () => [],
  pasteSeparator: () => /[,，\r\n]+/,
  allowCreate: false,
  disabled: false,
  loading: false,
  noDataText: '无匹配选项',
  loadErrorMessage: '候选加载失败，请重试',
  validationErrorMessage: '选项校验失败，请重新粘贴',
})
const emit = defineEmits<{
  'update:modelValue': [value: string[]]
  change: [value: string[]]
}>()
const select = ref<InstanceType<typeof AppSelect>>()
const remoteOptions = ref<AppMultiSelectOption[]>([])
const selectedOptions = ref<AppMultiSelectOption[]>([])
const query = ref('')
const searching = ref(false)
const validating = ref(false)
const searchError = ref('')
const pasteError = ref('')
const error = computed(() => pasteError.value || searchError.value)
const busy = computed(() => props.loading || searching.value || validating.value)
const searchRequests = createLatestRequestGuard()
const pasteRequests = createLatestRequestGuard()

function normalize(values: string[]): string[] {
  return [...new Set(values.map(value => (props.normalizeValue?.(value) ?? value).trim()).filter(Boolean))]
}
const candidates = computed(() => [
  ...props.options.filter(item => !props.loadOptions
    || item.label.toLowerCase().includes(query.value.toLowerCase())),
  ...remoteOptions.value,
])
const displayOptions = computed(() => {
  const items = new Map(selectedOptions.value.map(item => [item.value, item]))
  for (const value of normalize(props.modelValue)) {
    if (!items.has(value)) items.set(value, { value, label: value })
  }
  for (const item of candidates.value) items.set(item.value, item)
  return [...items.values()]
})

function cancelPaste() {
  pasteRequests.invalidate()
  validating.value = false
}
function commit(values: string[]) {
  const available = new Set(displayOptions.value.map(item => item.value))
  const accepted = normalize(values).filter(value => props.allowCreate || available.has(value))
  selectedOptions.value = displayOptions.value.filter(item => accepted.includes(item.value))
  emit('update:modelValue', accepted)
  emit('change', accepted)
}
function update(values: string[]) {
  if (props.disabled) return
  cancelPaste()
  pasteError.value = ''
  commit(values)
}

async function search(keyword: string) {
  query.value = keyword.trim()
  const request = searchRequests.begin()
  remoteOptions.value = []
  searchError.value = ''
  searching.value = false
  // Element Plus 确认选择后会清空搜索；此时仍须保留本次粘贴的拒绝原因。
  if (!query.value) return
  pasteError.value = ''
  if (!props.loadOptions) return
  searching.value = true
  try {
    const items = await props.loadOptions(query.value)
    if (searchRequests.isCurrent(request)) remoteOptions.value = items
  } catch (reason) {
    if (searchRequests.isCurrent(request)) searchError.value = getErrorMessage(reason, props.loadErrorMessage)
  } finally {
    if (searchRequests.isCurrent(request)) searching.value = false
  }
}

async function handlePaste(event: ClipboardEvent) {
  const text = event.clipboardData?.getData('text') ?? ''
  const parts = text.trim().split(props.pasteSeparator)
  if (parts.length < 2) return
  event.preventDefault()
  if (props.disabled) return
  cancelPaste()
  const request = pasteRequests.begin()
  validating.value = true
  pasteError.value = ''
  const values = normalize(parts)
  const selected = new Set(normalize(props.modelValue))
  const requested = values.filter(value => !selected.has(value))
  try {
    const resolved = !requested.length ? [] : props.resolveValues ? await props.resolveValues(requested)
      : requested.flatMap(value => {
        const item = displayOptions.value.find(option => option.value === value)
        return item ? [item] : props.allowCreate ? [{ value, label: value }] : []
      })
    if (!pasteRequests.isCurrent(request)) return
    // 校验器只能确认本次请求中的值，不能夹带其他选项或改变粘贴顺序。
    const items = resolved.filter(item => requested.includes(item.value))
    const accepted = new Set([...selected, ...items.map(item => item.value)])
    const rejected = values.filter(value => !accepted.has(value))
    remoteOptions.value = [...remoteOptions.value.filter(item => !accepted.has(item.value)), ...items]
    if (items.length) commit([...props.modelValue, ...values.filter(value => accepted.has(value))])
    if (rejected.length) pasteError.value = props.rejectedMessage?.(rejected)
      ?? `未加入无效选项：${rejected.slice(0, 5).join('、')}${rejected.length > 5 ? '等' : ''}`
  } catch (reason) {
    if (pasteRequests.isCurrent(request)) pasteError.value = getErrorMessage(reason, props.validationErrorMessage)
  } finally {
    if (pasteRequests.isCurrent(request)) validating.value = false
  }
}

watch(() => props.modelValue, () => {
  cancelPaste()
  const selected = new Set(normalize(props.modelValue))
  selectedOptions.value = displayOptions.value.filter(item => selected.has(item.value))
}, { deep: true, immediate: true })
watch(() => props.contextKey, () => {
  searchRequests.invalidate()
  cancelPaste()
  remoteOptions.value = []
  selectedOptions.value = []
  query.value = ''
  searching.value = false
  searchError.value = ''
  pasteError.value = ''
})
watch(() => props.disabled, value => {
  if (value) cancelPaste()
})
onBeforeUnmount(() => {
  searchRequests.invalidate()
  cancelPaste()
})
defineExpose({ focus: () => select.value?.focus(), blur: () => select.value?.blur() })
</script>

<template>
  <div class="app-multi-select" @paste="handlePaste">
    <AppSelect
      ref="select"
      v-bind="$attrs"
      :model-value="modelValue"
      multiple
      :allow-create="allowCreate"
      :remote="Boolean(loadOptions)"
      :remote-method="search"
      :loading="busy"
      :disabled="disabled"
      :no-data-text="error || noDataText"
      @update:model-value="update"
    >
      <template v-for="name in Object.keys($slots).filter(name => name !== 'default')" #[name]="scope">
        <slot :name="name" v-bind="scope || {}" />
      </template>
      <template #default>
        <el-option v-for="item in displayOptions" :key="item.value" :label="item.label" :value="item.value" />
      </template>
    </AppSelect>
    <div v-if="error" class="app-multi-select__error app-caption-text" role="alert">{{ error }}</div>
  </div>
</template>

<style scoped>
.app-multi-select { width: 100%; min-width: 0; }
.app-multi-select__error {
  margin-top: var(--app-space-1);
  color: var(--app-danger-text);
  overflow-wrap: anywhere;
}
</style>
