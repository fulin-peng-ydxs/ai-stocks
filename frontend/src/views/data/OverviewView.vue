<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  getOverview, getCatalog, getDimensions, getStockQuality,
  type Overview, type CatalogTable, type Dimension, type StockQuality,
} from '@/api/data'

const router = useRouter()
const loading = ref(false)
const error = ref('')
const ov = ref<Overview | null>(null)
const tables = ref<CatalogTable[]>([])
const dims = ref<Dimension[]>([])

// 逐股质量
const sq = ref<StockQuality | null>(null)
const sqLoading = ref(false)
const sqCodes = ref('')
const sqPage = ref(1)
const sqSize = ref(20)

const DIM_STATUS: Record<string, { label: string; type: 'success' | 'info' | 'warning' }> = {
  collected: { label: '已采集', type: 'success' },
  partial: { label: '部分覆盖', type: 'warning' },
  planned: { label: '规划中', type: 'info' },
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [o, c, d] = await Promise.all([getOverview(), getCatalog(), getDimensions()])
    ov.value = o
    tables.value = c.tables
    dims.value = d.dimensions
    await loadSq()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function loadSq() {
  sqLoading.value = true
  try {
    sq.value = await getStockQuality({
      codes: sqCodes.value.trim() || undefined, page: sqPage.value, size: sqSize.value,
    })
  } finally {
    sqLoading.value = false
  }
}
function searchSq() { sqPage.value = 1; loadSq() }
function gotoGap() { router.push('/data/ingest') }

onMounted(load)
</script>

<template>
  <div class="v-page">
    <div class="page-head">
      <h2>数据概览</h2>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>

    <div class="v-scroll">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

      <template v-else>
        <!-- KPI -->
        <el-row :gutter="14" class="stat-row" v-loading="loading">
          <el-col :span="5">
            <el-card shadow="never" class="stat">
              <div class="stat-label">最新交易日</div>
              <div class="stat-val">{{ (ov?.latest_trade_date ?? '').slice(0, 10) || '—' }}</div>
            </el-card>
          </el-col>
          <el-col :span="5">
            <el-card shadow="never" class="stat">
              <div class="stat-label">股票数（在市 / 退市）</div>
              <div class="stat-val">{{ ov?.codes.active ?? '—' }}<span class="sub"> / {{ ov?.codes.delisted ?? '—' }}</span></div>
            </el-card>
          </el-col>
          <el-col :span="5">
            <el-card shadow="never" class="stat">
              <div class="stat-label">日线总行数</div>
              <div class="stat-val">{{ ov?.bar_rows?.toLocaleString() ?? '—' }}</div>
            </el-card>
          </el-col>
          <el-col :span="4">
            <el-card shadow="never" class="stat">
              <div class="stat-label">未解决质检</div>
              <div class="stat-val" :class="{ danger: (ov?.quality.by_severity?.high ?? 0) > 0, warn: (ov?.quality.open ?? 0) > 0 }">
                {{ ov?.quality.open ?? '—' }}
              </div>
              <div class="stat-foot" v-if="ov?.quality.open">
                高{{ ov.quality.by_severity?.high ?? 0 }} 中{{ ov.quality.by_severity?.mid ?? 0 }} 低{{ ov.quality.by_severity?.low ?? 0 }}
              </div>
            </el-card>
          </el-col>
          <el-col :span="5">
            <el-card shadow="never" class="stat clickable" @click="gotoGap">
              <div class="stat-label">缺口提示</div>
              <div class="stat-val" :class="{ warn: (ov?.gaps.stocks_with_gap ?? 0) > 0 }">
                {{ ov?.gaps.stocks_with_gap ?? '—' }}<span class="sub"> 只</span>
              </div>
              <div class="stat-foot" v-if="ov?.gaps">缺口日 {{ ov.gaps.gap_days_total }} · 点此补数</div>
            </el-card>
          </el-col>
        </el-row>

        <!-- 基础数据表目录（数据字典）-->
        <el-card shadow="never" class="blk" header="基础数据表（数据字典）">
          <el-table :data="tables" size="small">
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="expand">
                  <div class="exp-line"><b>作用：</b>{{ row.purpose }}</div>
                  <div class="exp-line" v-if="row.relations?.length"><b>关联：</b>{{ row.relations.join('；') }}</div>
                  <el-table :data="row.fields" size="small" class="fld-tbl">
                    <el-table-column label="字段" prop="name" width="150" />
                    <el-table-column label="中文名" prop="name_cn" width="120" />
                    <el-table-column label="类型" prop="type" width="100" />
                    <el-table-column label="说明" prop="desc" show-overflow-tooltip />
                  </el-table>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="表" width="170">
              <template #default="{ row }"><span class="mono">{{ row.table }}</span></template>
            </el-table-column>
            <el-table-column label="名称" prop="name_cn" width="120" />
            <el-table-column label="行数" width="110">
              <template #default="{ row }">{{ row.rows.toLocaleString() }}</template>
            </el-table-column>
            <el-table-column label="最新数据时间" width="170">
              <template #default="{ row }">{{ (row.latest_time || '—').slice(0, 19) }}</template>
            </el-table-column>
            <el-table-column label="质量" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.open_issues > 0" type="warning" size="small" effect="plain">{{ row.open_issues }} 待处理</el-tag>
                <el-tag v-else type="success" size="small" effect="plain">正常</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="作用" prop="purpose" show-overflow-tooltip />
          </el-table>
        </el-card>

        <!-- 数据维度注册表 -->
        <el-card shadow="never" class="blk" header="数据维度注册表（可扩展）">
          <el-table :data="dims" size="small">
            <el-table-column label="维度" prop="name_cn" width="120" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="DIM_STATUS[row.status]?.type ?? 'info'" size="small" effect="plain">
                  {{ DIM_STATUS[row.status]?.label ?? row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="数据源" prop="source" width="180" />
            <el-table-column label="关联表" width="200">
              <template #default="{ row }"><span class="mono">{{ row.tables.join(', ') || '—' }}</span></template>
            </el-table-column>
            <el-table-column label="说明" prop="descr" show-overflow-tooltip />
          </el-table>
        </el-card>

        <!-- 逐股数据质量 -->
        <el-card shadow="never" class="blk">
          <template #header>
            <div class="blk-head">
              <span>逐股数据质量（鲜活度 / 关键字段达标 / 缺口）</span>
              <span class="hint">最新交易日 {{ (sq?.latest_trade_date || '—').slice(0, 10) }}</span>
            </div>
          </template>
          <div class="sq-bar">
            <el-input v-model="sqCodes" placeholder="按代码筛选，逗号分隔，如 600000.SH,000001.SZ" clearable
                      style="max-width: 380px" @keyup.enter="searchSq" @clear="searchSq" />
            <el-button type="primary" plain @click="searchSq">查询</el-button>
          </div>
          <el-table :data="sq?.list ?? []" size="small" v-loading="sqLoading" max-height="360">
            <el-table-column label="代码" prop="code" width="120" />
            <el-table-column label="名称" prop="name" width="110" />
            <el-table-column label="最新数据" width="120">
              <template #default="{ row }">{{ (row.latest_date || '—').slice(0, 10) }}</template>
            </el-table-column>
            <el-table-column label="鲜活" width="80">
              <template #default="{ row }">
                <el-tag :type="row.is_fresh ? 'success' : 'danger'" size="small" effect="plain">
                  {{ row.is_fresh ? '最新' : '滞后' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="总市值" width="90">
              <template #default="{ row }">
                <el-tag :type="row.total_mv_ok ? 'success' : 'info'" size="small" effect="plain">
                  {{ row.total_mv_ok ? '达标' : '缺' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="缺口日" width="90">
              <template #default="{ row }">
                <span :class="{ 'txt-warn': row.gap_days > 0 }">{{ row.gap_days }}</span>
              </template>
            </el-table-column>
            <el-table-column label="未解决问题" width="100">
              <template #default="{ row }">
                <span :class="{ 'txt-warn': row.open_issues > 0 }">{{ row.open_issues }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="pager">
            <el-pagination layout="total, prev, pager, next" :total="sq?.total ?? 0"
                           :current-page="sqPage" :page-size="sqSize" background
                           @current-change="(p: number) => { sqPage = p; loadSq() }" />
          </div>
        </el-card>
      </template>
    </div>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.page-head h2 { margin: 0; font-size: 20px; }
.stat-row { margin-bottom: 16px; }
.stat { text-align: center; }
.stat :deep(.el-card__body) { padding: 14px 8px; }
.stat.clickable { cursor: pointer; transition: box-shadow .15s; }
.stat.clickable:hover { box-shadow: 0 0 0 1px var(--el-color-primary) inset; }
.stat-label { color: var(--el-text-color-secondary); font-size: 13px; }
.stat-val { font-size: 17px; font-weight: 700; color: var(--el-text-color-primary); margin-top: 6px; white-space: nowrap; }
.stat-val .sub { font-size: 14px; font-weight: 400; color: var(--el-text-color-secondary); }
.stat-val.warn { color: #e6a23c; }
.stat-val.danger { color: #f56c6c; }
.stat-foot { font-size: 11px; color: var(--el-text-color-secondary); margin-top: 4px; }
.blk { margin-bottom: 16px; }
.blk-head { display: flex; justify-content: space-between; align-items: center; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.mono { font-family: var(--el-font-family-mono, monospace); font-size: 12px; }
.expand { padding: 6px 14px; }
.exp-line { font-size: 13px; margin-bottom: 6px; color: var(--el-text-color-regular); }
.fld-tbl { margin-top: 8px; }
.sq-bar { display: flex; gap: 10px; margin-bottom: 12px; }
.txt-warn { color: #e6a23c; font-weight: 600; }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
</style>
