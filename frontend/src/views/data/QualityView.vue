<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getDataQuality, fixQualityIssue, createTask,
  ISSUE_TYPE_LABEL, SEVERITY_LABEL, ISSUE_STATUS_LABEL,
  type DataQuality, type QualityIssue,
} from '@/api/data'

const loading = ref(false)
const data = ref<DataQuality | null>(null)
const page = ref(1)
const size = ref(50)
const filters = ref<{ issue_type: string; severity: string; status: string; code: string }>(
  { issue_type: '', severity: '', status: 'open', code: '' })

const sevType: Record<string, 'danger' | 'warning' | 'info'> = { high: 'danger', mid: 'warning', low: 'info' }
const statType: Record<string, 'info' | 'warning' | 'success'> = {
  open: 'info', fixing: 'warning', resolved: 'success', ignored: 'info',
}

async function load() {
  loading.value = true
  try {
    data.value = await getDataQuality({
      issue_type: filters.value.issue_type || undefined,
      severity: filters.value.severity || undefined,
      status: filters.value.status || undefined,
      code: filters.value.code.trim() || undefined,
      page: page.value, size: size.value,
    })
  } finally {
    loading.value = false
  }
}

// 筛选变更自动触发（列表交互标准）
watch(() => [filters.value.issue_type, filters.value.severity, filters.value.status], () => { page.value = 1; load() })

async function fixOne(row: QualityIssue) {
  try {
    await fixQualityIssue(row.id)
    ElMessage.success('已提交修复任务，完成后该问题将标记为已解决')
    row.status = 'fixing'
  } catch { /* 拦截器弹错 */ }
}

function rowClass({ row }: { row: QualityIssue }): string {
  return row.status === 'resolved' || row.status === 'ignored' ? 'row-done' : ''
}

async function runVerify() {
  try {
    await createTask('verify')
    ElMessage.success('已提交数据体检，完成后刷新可见新问题')
  } catch { /* */ }
}

onMounted(load)
</script>

<template>
  <div class="v-page">
    <div class="page-head">
      <h2>数据质量</h2>
      <div>
        <el-button type="primary" plain @click="runVerify">一键体检</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="filter-bar">
      <el-select v-model="filters.status" placeholder="状态" clearable style="width: 120px">
        <el-option v-for="(l, k) in ISSUE_STATUS_LABEL" :key="k" :label="l" :value="k" />
      </el-select>
      <el-select v-model="filters.severity" placeholder="严重度" clearable style="width: 120px">
        <el-option v-for="(l, k) in SEVERITY_LABEL" :key="k" :label="l" :value="k" />
      </el-select>
      <el-select v-model="filters.issue_type" placeholder="问题类型" clearable style="width: 150px">
        <el-option v-for="(l, k) in ISSUE_TYPE_LABEL" :key="k" :label="l" :value="k" />
      </el-select>
      <el-input v-model="filters.code" placeholder="股票代码" clearable style="width: 160px"
                @keyup.enter="() => { page = 1; load() }" @clear="() => { page = 1; load() }" />
      <div class="summary">
        <el-tag v-for="s in data?.summary ?? []" :key="s.issue_type" size="small" type="warning" effect="plain" class="sm-tag">
          {{ ISSUE_TYPE_LABEL[s.issue_type] ?? s.issue_type }}: {{ s.n }}
        </el-tag>
      </div>
    </div>

    <el-card shadow="never" class="v-grow">
      <el-table :data="data?.list ?? []" size="small" height="100%" v-loading="loading"
                :row-class-name="rowClass">
        <el-table-column label="严重度" width="90">
          <template #default="{ row }">
            <el-tag :type="sevType[row.severity] ?? 'info'" size="small" effect="dark">{{ SEVERITY_LABEL[row.severity] ?? row.severity }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="代码" prop="code" width="120" />
        <el-table-column label="日期" width="110">
          <template #default="{ row }">{{ (row.trade_date || '—').slice(0, 10) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="120">
          <template #default="{ row }">{{ ISSUE_TYPE_LABEL[row.issue_type] ?? row.issue_type }}</template>
        </el-table-column>
        <el-table-column label="详情" prop="detail" show-overflow-tooltip />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statType[row.status] ?? 'info'" size="small" effect="plain">{{ ISSUE_STATUS_LABEL[row.status] ?? row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="检出时间" width="160">
          <template #default="{ row }">{{ (row.detected_at || '').slice(0, 19) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'open' || row.status === 'fixing'" type="primary" size="small" link
                       :disabled="row.status === 'fixing'" @click="fixOne(row)">
              {{ row.status === 'fixing' ? '修复中…' : '重拉/重算' }}
            </el-button>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <div class="pager">
      <el-pagination layout="total, prev, pager, next" :total="data?.total ?? 0" background
                     :current-page="page" :page-size="size" @current-change="(p: number) => { page = p; load() }" />
    </div>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.page-head h2 { margin: 0; font-size: 20px; }
.filter-bar { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.summary { margin-left: auto; }
.sm-tag { margin-left: 6px; }
.muted { color: var(--el-text-color-secondary); }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
:deep(.row-done) { opacity: 0.55; }
</style>
