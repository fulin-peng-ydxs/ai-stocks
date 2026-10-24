<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppDetailDrawer from '@/components/AppDetailDrawer.vue'
import AppReorderList from '@/components/AppReorderList.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import AppDetailSection from '@/components/AppDetailSection.vue'
import {
  listScheduleDownstream, saveScheduleDownstreamOrder, taskDisplayLabel,
  type ScheduledJob, type TriggerCondition,
} from '@/api/data'
import { useFormChangeTracker } from '@/composables/useFormChangeTracker'
import { createLatestRequestGuard } from '@/utils/latestRequestGuard'
import { getErrorMessage } from '@/utils/error'

const props = defineProps<{ modelValue: boolean; job: ScheduledJob | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
const jobs = ref<ScheduledJob[]>([])
const revision = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const saveError = ref('')
const requests = createLatestRequestGuard()
const { hasChanges, captureBaseline, clearBaseline } = useFormChangeTracker(
  () => jobs.value.map(job => job.id),
)
const state = computed(() => loading.value ? 'loading' : error.value ? 'error'
  : jobs.value.length ? 'ready' : 'empty')
const conditionLabels: Record<TriggerCondition, string> = {
  success: '成功后', failure: '失败后', completion: '完成后',
}
const delayUnits = { second: '秒', minute: '分钟', hour: '小时' }
function delayText(job: ScheduledJob): string {
  const delay = job.dependency_delay
  return delay.value === 0 ? '立即触发' : `延迟 ${delay.value} ${delayUnits[delay.unit]}`
}
async function load() {
  if (!props.job || !props.modelValue || saving.value) return
  const request = requests.begin()
  loading.value = true
  error.value = ''
  saveError.value = ''
  clearBaseline()
  try {
    const result = await listScheduleDownstream(props.job.id)
    if (!requests.isCurrent(request)) return
    jobs.value = result.jobs
    revision.value = result.revision
    captureBaseline()
  } catch (cause) {
    if (requests.isCurrent(request)) error.value = getErrorMessage(cause, '下游任务加载失败')
  } finally {
    if (requests.isCurrent(request)) loading.value = false
  }
}
async function confirmDiscard(): Promise<boolean> {
  if (saving.value) return false
  if (!hasChanges.value) return true
  try {
    await ElMessageBox.confirm('下游触发顺序尚未保存，确认放弃修改？', '放弃排序修改', {
      confirmButtonType: 'danger',
      type: 'warning', confirmButtonText: '放弃修改', cancelButtonText: '继续调整',
    })
    return true
  } catch { return false }
}
async function close() {
  if (await confirmDiscard()) emit('update:modelValue', false)
}
async function beforeClose(done: () => void) {
  if (await confirmDiscard()) done()
}
async function refresh() {
  if (await confirmDiscard()) await load()
}
function reorder(next: ScheduledJob[]) {
  if (!loading.value && !saving.value) jobs.value = next
}
async function save() {
  if (!props.job || saving.value || loading.value || !hasChanges.value || jobs.value.length < 2) return
  saving.value = true
  saveError.value = ''
  const request = requests.begin()
  try {
    const result = await saveScheduleDownstreamOrder(
      props.job.id, jobs.value.map(job => job.id), revision.value,
    )
    if (!requests.isCurrent(request)) return
    jobs.value = result.jobs
    revision.value = result.revision
    captureBaseline()
    ElMessage.success('下游触发顺序已保存，仅对新生成的触发事件生效')
  } catch (cause) {
    if (requests.isCurrent(request)) saveError.value = getErrorMessage(cause, '保存失败，请重试')
  } finally {
    if (requests.isCurrent(request)) saving.value = false
  }
}
watch(() => [props.modelValue, props.job?.id] as const, () => {
  requests.invalidate()
  loading.value = false
  saving.value = false
  jobs.value = []
  clearBaseline()
  if (props.modelValue) void load()
}, { immediate: true })
onBeforeUnmount(() => requests.invalidate())
</script>

<template>
  <AppDetailDrawer
    :model-value="modelValue"
    :title="job ? `${job.name} · 下游任务` : '下游任务'"
    size="xl"
    :state="state"
    :state-title="loading ? '正在加载下游任务…' : error ? '下游任务加载失败' : '暂无直接下游任务'"
    :state-description="error || '在其他任务的编辑表单中，选择当前任务作为上游即可建立依赖。'"
    :retry="Boolean(error)"
    :before-close="beforeClose"
    @update:model-value="emit('update:modelValue', $event)"
    @retry="load"
  >
    <p class="app-caption-text">按各任务的条件和延迟触发；同一次上游执行产生、到期时间相同的任务按以下顺序尝试触发，执行时可按资源规则并行。调整仅影响新生成的触发事件。</p>
    <AppReorderList
      :items="jobs" :item-key="item => item.id" :item-label="item => item.name"
      label="下游任务触发顺序" :disabled="saving || loading" @reorder="reorder"
    >
      <template #default="{ item, index }">
        <AppDetailSection :title="`${index + 1}. ${item.name}`">
          <span class="app-inline-info">
            <el-tag size="small" effect="plain" :type="item.enabled ? 'success' : 'info'">
              {{ item.enabled ? '已启用' : '已停用 · 不自动触发' }}
            </el-tag>
            <span>{{ taskDisplayLabel(item.task_type, item.params) }}</span>
          </span>
          <p>{{ conditionLabels[item.dependency_condition || 'completion'] }} · {{ delayText(item) }}</p>
        </AppDetailSection>
      </template>
    </AppReorderList>
    <template #footer>
      <AppStatusNotice v-if="saveError" :title="saveError" tone="error" size="compact" />
      <el-button :loading="loading" :disabled="saving" @click="refresh">刷新</el-button>
      <el-button :disabled="saving" @click="close">关闭</el-button>
      <el-button v-permission="'data-schedule:manage'" type="primary" :loading="saving"
        :disabled="!hasChanges || loading || jobs.length < 2" @click="save">保存顺序</el-button>
    </template>
  </AppDetailDrawer>
</template>
