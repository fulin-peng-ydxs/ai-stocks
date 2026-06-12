<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getDataStatus, listTasks, createTask, getTask, getTaskLogs, resumeTask,
  TASK_LABEL, STATUS_LABEL,
  type DataStatus, type AsyncTask, type TaskType, type TaskStatus, type TaskLogLine,
} from '@/api/data'

const loading = ref(false)
const status = ref<DataStatus | null>(null)
const tasks = ref<AsyncTask[]>([])

const statusType: Record<TaskStatus, 'success' | 'danger' | 'info' | 'warning'> = {
  done: 'success', failed: 'danger', running: 'warning', pending: 'info', interrupted: 'danger',
}
const updateLogType: Record<string, 'success' | 'danger' | 'info'> = { success: 'success', failed: 'danger' }
const writeRunning = computed(() =>
  tasks.value.some((t) => ['pending', 'running'].includes(t.status)
    && ['update', 'backfill', 'ingest_date', 'ingest_codes', 'fix'].includes(t.task_type)))

// ── 更多选项对话框 ──
const optDlg = ref(false)
const optType = ref<TaskType>('ingest_date')
const optForm = ref<{ codes: string; date_start: string; date_end: string; years: number | null }>(
  { codes: '', date_start: '', date_end: '', years: null })

function openOptions(type: TaskType) {
  optType.value = type
  optForm.value = { codes: '', date_start: '', date_end: '', years: null }
  optDlg.value = true
}

async function submitOptions() {
  const f = optForm.value
  const codes = f.codes.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean)
  const params: Record<string, unknown> = {}
  if (codes.length) params.codes = codes
  if (optType.value === 'ingest_date') {
    if (!f.date_start) { ElMessage.warning('请选择起始日期'); return }
    params.date_start = f.date_start
    params.date_end = f.date_end || f.date_start
  } else if (optType.value === 'backfill') {
    if (f.years) params.years = f.years
  } else if (optType.value === 'ingest_codes') {
    if (!codes.length) { ElMessage.warning('请填写股票代码'); return }
  }
  optDlg.value = false
  await submit(optType.value, params)
}

// ── 提交任务 ──
async function submit(type: TaskType, params?: Record<string, unknown>, confirm?: string) {
  if (confirm) {
    try { await ElMessageBox.confirm(confirm, TASK_LABEL[type], { type: 'warning' }) } catch { return }
  }
  try {
    const { task_id } = await createTask(type, params)
    ElMessage.success(`已提交：${TASK_LABEL[type]}`)
    await refreshTasks()
    openLogs(task_id)
  } catch (e) {
    /* 409 等错误由 http 拦截器已弹出提示 */
  }
}

async function refreshTasks() { try { tasks.value = (await listTasks(15)).tasks } catch { /**/ } }

async function load() {
  loading.value = true
  try { status.value = await getDataStatus() } finally { loading.value = false }
  await refreshTasks()
}

// ── 续跑 ──
async function resume(t: AsyncTask) {
  try {
    await resumeTask(t.id)
    ElMessage.success('已续跑')
    await refreshTasks()
    openLogs(t.id)
  } catch { /* 拦截器弹错 */ }
}

// ── 实时日志抽屉 ──
const logDrawer = ref(false)
const logTask = ref<AsyncTask | null>(null)
const logs = ref<TaskLogLine[]>([])
const autoScroll = ref(true)
const logBody = ref<HTMLElement | null>(null)
let logTimer: number | undefined
let lastSeq = 0

async function openLogs(id: string) {
  logDrawer.value = true
  logs.value = []
  lastSeq = 0
  logTask.value = await getTask(id).catch(() => null)
  pollLogs(id)
}

function pollLogs(id: string) {
  if (logTimer) clearTimeout(logTimer)
  const tick = async () => {
    try {
      logTask.value = await getTask(id)
      const { logs: lines } = await getTaskLogs(id, lastSeq)
      if (lines.length) {
        logs.value.push(...lines)
        lastSeq = lines[lines.length - 1].seq
        if (autoScroll.value) requestAnimationFrame(() => {
          if (logBody.value) logBody.value.scrollTop = logBody.value.scrollHeight
        })
      }
      const st = logTask.value?.status
      if (st === 'done' || st === 'failed' || st === 'interrupted') {
        await refreshTasks()
        if (st === 'done') await load()
        return
      }
    } catch { /* 下一拍重试 */ }
    logTimer = window.setTimeout(tick, 1200)
  }
  tick()
}

function closeLogs() { logDrawer.value = false; if (logTimer) clearTimeout(logTimer) }
onUnmounted(() => { if (logTimer) clearTimeout(logTimer) })
onMounted(load)
</script>

<template>
  <div class="v-page">
    <div class="page-head">
      <h2>数据采集与任务</h2>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>

    <div class="v-scroll">
      <!-- 采集区 -->
      <el-card shadow="never" class="blk">
        <template #header>
          <div class="blk-head"><span>数据采集</span>
            <span class="hint">后台异步执行，可离开页面；点任务看实时日志。同类采集任务不可并发。</span></div>
        </template>
        <div class="act-grid">
          <div class="act">
            <div class="act-t">增量更新</div>
            <div class="act-d">拉取至最新交易日</div>
            <el-button type="primary" plain size="small" :disabled="writeRunning" @click="submit('update')">执行</el-button>
            <el-button text size="small" @click="openOptions('ingest_codes')">指定股票…</el-button>
          </div>
          <div class="act">
            <div class="act-t">历史补数</div>
            <div class="act-d">回补缺失历史（可能较久）</div>
            <el-button type="primary" plain size="small" :disabled="writeRunning"
                       @click="submit('backfill', undefined, '历史补数耗时可能较长，确认开始？')">执行</el-button>
            <el-button text size="small" @click="openOptions('backfill')">更多选项…</el-button>
          </div>
          <div class="act">
            <div class="act-t">指定日期采集</div>
            <div class="act-d">补单日 / 区间行情</div>
            <el-button type="primary" plain size="small" :disabled="writeRunning" @click="openOptions('ingest_date')">设置并执行</el-button>
          </div>
        </div>
      </el-card>

      <!-- 重算区 -->
      <el-card shadow="never" class="blk">
        <template #header><div class="blk-head"><span>评分与体检</span>
          <span class="hint">数据变更后评分快照惰性失效；体检结果写入「数据质量」。</span></div></template>
        <div class="act-grid">
          <div class="act">
            <div class="act-t">重算评分</div>
            <div class="act-d">标记评分快照失效，下次访问重算</div>
            <el-button plain size="small" @click="submit('recompute')">执行</el-button>
          </div>
          <div class="act">
            <div class="act-t">数据体检</div>
            <div class="act-d">结构/价格/契约校验 + 质量扫描</div>
            <el-button plain size="small" @click="submit('verify')">执行</el-button>
          </div>
        </div>
      </el-card>

      <!-- 任务中心 -->
      <el-card shadow="never" class="blk" header="任务中心（点击查看实时日志）">
        <el-table :data="tasks" size="small" max-height="300" @row-click="(r: AsyncTask) => openLogs(r.id)" class="clk-tbl">
          <el-table-column label="类型" width="120">
            <template #default="{ row }">{{ TASK_LABEL[row.task_type as TaskType] ?? row.task_type }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="statusType[row.status as TaskStatus] ?? 'info'" size="small" effect="dark">
                {{ STATUS_LABEL[row.status as TaskStatus] ?? row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="进度" width="150">
            <template #default="{ row }">
              <el-progress :percentage="Math.round((row.progress ?? 0) * 100)" :stroke-width="10"
                :status="row.status === 'failed' || row.status === 'interrupted' ? 'exception' : row.status === 'done' ? 'success' : undefined" />
            </template>
          </el-table-column>
          <el-table-column label="信息" prop="message" show-overflow-tooltip />
          <el-table-column label="时间" width="160">
            <template #default="{ row }">{{ (row.updated_at || '').slice(0, 19) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button v-if="row.status === 'interrupted'" type="warning" size="small" link
                         @click.stop="resume(row)">续跑</el-button>
              <el-button size="small" link @click.stop="openLogs(row.id)">日志</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 采集更新日志（中文化时间线）-->
      <el-card shadow="never" class="blk" header="最近采集日志">
        <el-table :data="status?.recent_updates ?? []" size="small" max-height="260">
          <el-table-column label="目标表" prop="table_name" width="150" />
          <el-table-column label="数据源" width="100">
            <template #default="{ row }">{{ row.source === 'akshare' ? 'AKShare' : row.source === 'baostock' ? 'BaoStock' : row.source }}</template>
          </el-table-column>
          <el-table-column label="结果" width="90">
            <template #default="{ row }">
              <el-tag :type="updateLogType[row.status] ?? 'info'" size="small" effect="plain">
                {{ row.status === 'success' ? '成功' : row.status === 'failed' ? '失败' : row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="行数" prop="row_count" width="90" />
          <el-table-column label="时间" width="180">
            <template #default="{ row }">{{ (row.updated_at || '').slice(0, 19) }}</template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>

    <!-- 更多选项对话框 -->
    <el-dialog v-model="optDlg" :title="`${TASK_LABEL[optType]} · 更多选项`" width="460px">
      <el-form label-width="92px">
        <el-form-item v-if="optType === 'ingest_date'" label="起始日期">
          <el-date-picker v-model="optForm.date_start" type="date" value-format="YYYY-MM-DD" placeholder="必填" />
        </el-form-item>
        <el-form-item v-if="optType === 'ingest_date'" label="结束日期">
          <el-date-picker v-model="optForm.date_end" type="date" value-format="YYYY-MM-DD" placeholder="留空=仅起始日" />
        </el-form-item>
        <el-form-item v-if="optType === 'backfill'" label="回填年限">
          <el-input-number v-model="optForm.years" :min="1" :max="30" placeholder="留空=默认" />
        </el-form-item>
        <el-form-item label="指定股票">
          <el-input v-model="optForm.codes" type="textarea" :rows="2"
                    placeholder="可选；逗号分隔，如 600000.SH,000001.SZ（留空=全市场）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="optDlg = false">取消</el-button>
        <el-button type="primary" @click="submitOptions">执行</el-button>
      </template>
    </el-dialog>

    <!-- 实时日志抽屉 -->
    <el-drawer v-model="logDrawer" :title="logTask ? `${TASK_LABEL[logTask.task_type] ?? logTask.task_type} · 实时日志` : '实时日志'"
               size="46%" @close="closeLogs">
      <div v-if="logTask" class="log-meta">
        <el-tag :type="statusType[logTask.status] ?? 'info'" size="small" effect="dark">{{ STATUS_LABEL[logTask.status] }}</el-tag>
        <span class="lm-msg">{{ logTask.message }}</span>
        <el-progress :percentage="Math.round((logTask.progress ?? 0) * 100)" :stroke-width="8" style="flex:1" />
        <el-checkbox v-model="autoScroll" size="small">自动滚动</el-checkbox>
      </div>
      <div ref="logBody" class="log-body">
        <div v-for="l in logs" :key="l.seq" class="log-line" :class="l.level">
          <span class="lt">{{ (l.ts || '').slice(11, 19) }}</span>
          <span class="lm">{{ l.message }}</span>
        </div>
        <div v-if="!logs.length" class="log-empty">暂无日志…</div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.page-head h2 { margin: 0; font-size: 20px; }
.blk { margin-bottom: 16px; }
.blk-head { display: flex; justify-content: space-between; align-items: center; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.act-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.act { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 12px 14px; }
.act-t { font-weight: 600; }
.act-d { font-size: 12px; color: var(--el-text-color-secondary); margin: 4px 0 10px; }
.clk-tbl :deep(tbody tr) { cursor: pointer; }
.log-meta { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.lm-msg { font-size: 12px; color: var(--el-text-color-secondary); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-body { height: calc(100% - 46px); overflow: auto; background: var(--el-fill-color-darker); border-radius: 6px; padding: 10px; font-family: var(--el-font-family-mono, monospace); font-size: 12px; }
.log-line { display: flex; gap: 10px; padding: 1px 0; }
.log-line.warn { color: #e6a23c; }
.log-line.error { color: #f56c6c; }
.lt { color: var(--el-text-color-secondary); flex-shrink: 0; }
.log-empty { color: var(--el-text-color-secondary); text-align: center; padding: 20px; }
</style>
