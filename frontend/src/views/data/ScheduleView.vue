<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getScheduler, setScheduler, getSources, testSources,
  SOURCE_LABEL, type SchedulerStatus, type SourceStatus,
} from '@/api/data'

const loading = ref(false)
const sched = ref<SchedulerStatus | null>(null)
const form = ref<{ enabled: boolean; time: string }>({ enabled: false, time: '18:00' })
const saving = ref(false)

const sources = ref<SourceStatus[]>([])
const pinging = ref(false)

const lastResult = computed(() => sched.value?.last_result)

async function loadSched() {
  sched.value = await getScheduler()
  form.value = {
    enabled: sched.value.enabled,
    time: `${String(sched.value.cron_hour).padStart(2, '0')}:${String(sched.value.cron_minute).padStart(2, '0')}`,
  }
}

async function save() {
  const [h, m] = form.value.time.split(':').map((x) => parseInt(x, 10))
  saving.value = true
  try {
    sched.value = await setScheduler({ enabled: form.value.enabled, cron_hour: h, cron_minute: m })
    ElMessage.success('定时配置已生效')
  } catch { /* */ } finally { saving.value = false }
}

async function loadSources(ping = false) {
  pinging.value = ping
  try {
    sources.value = (ping ? await testSources() : await getSources(false)).sources
  } finally {
    pinging.value = false
  }
}

async function load() {
  loading.value = true
  try { await Promise.all([loadSched(), loadSources(false)]) } finally { loading.value = false }
}

onMounted(load)
</script>

<template>
  <div class="v-page">
    <div class="page-head">
      <h2>调度与数据源</h2>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>

    <div class="v-scroll">
      <el-row :gutter="16">
        <!-- 定时采集 -->
        <el-col :span="12">
          <el-card shadow="never" class="blk" header="定时采集">
            <el-form label-width="100px">
              <el-form-item label="启用">
                <el-switch v-model="form.enabled" />
                <span class="hint">每个交易日按时自动跑日常流程（更新→榜单→预设筛选），非交易日跳过。</span>
              </el-form-item>
              <el-form-item label="执行时间">
                <el-time-picker v-model="form.time" value-format="HH:mm" format="HH:mm" placeholder="HH:mm" :clearable="false" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="saving" @click="save">保存并生效</el-button>
              </el-form-item>
            </el-form>
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="当前状态">
                <el-tag :type="sched?.enabled ? 'success' : 'info'" size="small" effect="plain">
                  {{ sched?.enabled ? '已启用' : '未启用' }}
                </el-tag>
                <el-tag v-if="sched?.running" type="success" size="small" effect="plain" style="margin-left:6px">调度器运行中</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="下次触发">{{ (sched?.next_run_time || '—').slice(0, 19) }}</el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>

        <!-- 数据源状态 -->
        <el-col :span="12">
          <el-card shadow="never" class="blk">
            <template #header>
              <div class="blk-head"><span>数据源状态</span>
                <el-button size="small" type="primary" plain :loading="pinging" @click="loadSources(true)">测试连通</el-button></div>
            </template>
            <div v-for="s in sources" :key="s.source" class="src">
              <span class="dot" :class="s.up === true ? 'up' : s.up === false ? 'down' : 'unknown'" />
              <span class="src-name">{{ SOURCE_LABEL[s.source] ?? s.source }}</span>
              <el-tag size="small" effect="plain" :type="s.role === 'primary' ? 'primary' : 'info'">
                {{ s.role === 'primary' ? '主源' : '备用' }}
              </el-tag>
              <span class="src-state">
                {{ s.up === true ? '连通' : s.up === false ? '不可达' : '未测试' }}
              </span>
              <span class="src-meta">最近成功 {{ (s.last_success_at || '—').slice(0, 19) }} · 超时 {{ s.timeout_sec }}s</span>
            </div>
            <div v-if="!sources.length" class="empty">点「测试连通」检查 AKShare / BaoStock 可达性</div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 最近一次执行结果 -->
      <el-card shadow="never" class="blk" header="最近一次定时执行结果">
        <template v-if="lastResult">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="执行时间">{{ (lastResult.run_at || '—').slice(0, 19) }}</el-descriptions-item>
            <el-descriptions-item label="结果">
              <el-tag v-if="lastResult.skipped" type="info" size="small" effect="plain">跳过（{{ lastResult.reason }}）</el-tag>
              <el-tag v-else :type="lastResult.ok ? 'success' : 'danger'" size="small" effect="plain">
                {{ lastResult.ok ? '成功' : '失败' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item v-if="lastResult.secs != null" label="耗时">{{ lastResult.secs }}s</el-descriptions-item>
            <el-descriptions-item v-if="lastResult.error" label="错误">{{ lastResult.error }}</el-descriptions-item>
          </el-descriptions>
          <el-table v-if="lastResult.steps" :data="lastResult.steps" size="small" class="step-tbl">
            <el-table-column label="步骤" prop="step" width="140" />
            <el-table-column label="状态" prop="status" width="90" />
            <el-table-column label="耗时(s)" prop="secs" width="90" />
          </el-table>
        </template>
        <div v-else class="empty">尚无定时执行记录（启用后到点自动触发，或服务运行期间未到执行时刻）。</div>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.page-head h2 { margin: 0; font-size: 20px; }
.blk { margin-bottom: 16px; }
.blk-head { display: flex; justify-content: space-between; align-items: center; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); margin-left: 10px; }
.src { display: flex; align-items: center; gap: 10px; padding: 9px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.src:last-child { border-bottom: none; }
.dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.dot.up { background: #67c23a; box-shadow: 0 0 0 3px rgba(103,194,58,.18); }
.dot.down { background: #f56c6c; box-shadow: 0 0 0 3px rgba(245,108,108,.18); }
.dot.unknown { background: #c0c4cc; }
.src-name { font-weight: 600; min-width: 78px; }
.src-state { font-size: 13px; }
.src-meta { font-size: 12px; color: var(--el-text-color-secondary); margin-left: auto; }
.empty { color: var(--el-text-color-secondary); font-size: 13px; padding: 10px 0; }
.step-tbl { margin-top: 10px; }
</style>
