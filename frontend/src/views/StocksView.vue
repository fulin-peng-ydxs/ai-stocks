<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listStocks, type StockBasic } from '@/api/stocks'
import {
  addMembers,
  createGroup,
  deleteGroup,
  getGroup,
  listGroups,
  removeMembers,
  updateGroup,
  type GroupDetail,
  type GroupMember,
  type GroupSummary,
} from '@/api/stockGroup'
import { useStockSet } from '@/stores/stockSet'
import { useTradeDates } from '@/composables/useTradeDates'
import TradeDatePicker from '@/components/TradeDatePicker.vue'

const router = useRouter()
const stockSet = useStockSet()
const { dataMax } = useTradeDates()

// ── 查询条件（普通查询）──
const loading = ref(false)
const q = ref('')
const board = ref('')
const excludeSt = ref(true)        // 默认排除 ST
const tradeDate = ref('')          // 交易日期（默认最新，展示当日涨跌幅）
const sortBy = ref('pct_chg')      // 服务端排序字段（默认涨跌幅）
const sortOrder = ref<'asc' | 'desc'>('asc')  // 默认正序
const page = ref(1)
const size = ref(20)
const total = ref(0)
const rows = ref<StockBasic[]>([])

// ST / 退市板块下「排除 ST」无意义（隐藏），其余板块默认排除 ST
watch(board, (b) => {
  excludeSt.value = b !== 'ST' && b !== '退市'
})
// 选交易日自动触发查询
watch(tradeDate, () => search())

async function load() {
  loading.value = true
  try {
    const data = await listStocks({
      q: q.value || undefined,
      board: board.value || undefined,
      exclude_st: excludeSt.value,
      trade_date: tradeDate.value || undefined,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
      page: page.value,
      size: size.value,
    })
    rows.value = data.list
    total.value = data.total
  } finally {
    loading.value = false
  }
}
function search() {
  page.value = 1
  load()
}
// 服务端排序（跨全量，而非仅当前页）
function onSortChange({ prop, order }: { prop: string; order: string | null }) {
  if (!order) {            // 取消排序 → 回默认涨跌幅正序
    sortBy.value = 'pct_chg'
    sortOrder.value = 'asc'
  } else {
    sortBy.value = prop
    sortOrder.value = order === 'descending' ? 'desc' : 'asc'
  }
  page.value = 1
  load()
}

// ── 分组查看 ──
const groups = ref<GroupSummary[]>([])
const activeGid = ref('')
const groupDetail = ref<GroupDetail | null>(null)
const groupLoading = ref(false)
const inGroupMode = computed(() => !!activeGid.value)

async function reloadGroups() {
  groups.value = await listGroups()
}
watch(activeGid, async (gid) => {
  cart.value = []   // 切换上下文清空选择
  if (!gid) {
    groupDetail.value = null
    return
  }
  await loadGroupDetail()
})
async function loadGroupDetail() {
  if (!activeGid.value) return
  groupLoading.value = true
  try {
    groupDetail.value = await getGroup(activeGid.value)
  } finally {
    groupLoading.value = false
  }
}
const groupRows = computed<GroupMember[]>(() => groupDetail.value?.members ?? [])

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return (v > 0 ? '+' : '') + v.toFixed(2) + '%'
}
function fmtPctRatio(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return (v > 0 ? '+' : '') + (v * 100).toFixed(2) + '%'
}
function pctClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'muted'
  return v > 0 ? 'up' : v < 0 ? 'down' : ''
}

// ── 持久化选择「购物车」：跨分页 / 跨搜索累积 ──
const cart = ref<{ code: string; name: string | null }[]>([])
const cartSet = computed(() => new Set(cart.value.map((c) => c.code)))
const cartCodes = computed(() => cart.value.map((c) => c.code))
function inCart(code: string): boolean {
  return cartSet.value.has(code)
}
function toggle(row: { code: string; name: string | null }) {
  const i = cart.value.findIndex((c) => c.code === row.code)
  if (i >= 0) cart.value.splice(i, 1)
  else cart.value.push({ code: row.code, name: row.name })
}
const curRows = computed<{ code: string; name: string | null }[]>(() =>
  inGroupMode.value ? groupRows.value : rows.value,
)
const allCurChecked = computed(() => curRows.value.length > 0 && curRows.value.every((r) => inCart(r.code)))
const someCurChecked = computed(() => curRows.value.some((r) => inCart(r.code)) && !allCurChecked.value)
function toggleAllCur(val: boolean) {
  if (val) {
    for (const r of curRows.value) if (!inCart(r.code)) cart.value.push({ code: r.code, name: r.name })
  } else {
    const codes = new Set(curRows.value.map((r) => r.code))
    cart.value = cart.value.filter((c) => !codes.has(c.code))
  }
}

// ── 进入详情：设置“当前集合” ──
function activeItems(): { code: string; name?: string | null }[] {
  if (inGroupMode.value) return groupRows.value.map((m) => ({ code: m.code, name: m.name }))
  return rows.value.map((r) => ({ code: r.code, name: r.name }))
}
function enterDetail(code: string) {
  const label = inGroupMode.value ? (groupDetail.value?.name ?? '分组') : '查询结果'
  stockSet.setSet(inGroupMode.value ? 'group' : 'list', activeItems(), label, activeGid.value)
  router.push(`/stocks/${code}`)
}
function viewCartOneByOne() {
  if (!cart.value.length) return
  stockSet.setSet('list', cart.value.map((c) => ({ code: c.code, name: c.name })), '勾选集')
  router.push(`/stocks/${cart.value[0].code}`)
}

// ── 存为新分组 ──
const createVisible = ref(false)
const createForm = ref<{ name: string; group_date: string; description: string }>({ name: '', group_date: '', description: '' })
const creating = ref(false)
function openCreate() {
  if (!cartCodes.value.length) return ElMessage.warning('请先勾选股票')
  createForm.value = { name: '', group_date: dataMax.value || '', description: '' }
  createVisible.value = true
}
async function doCreate() {
  if (!createForm.value.name.trim()) return ElMessage.warning('请输入分组名')
  creating.value = true
  try {
    const r = await createGroup({
      name: createForm.value.name.trim(),
      group_date: createForm.value.group_date || undefined,
      description: createForm.value.description,
      codes: cartCodes.value,
    })
    ElMessage.success(`已创建分组（${cartCodes.value.length} 只）`)
    createVisible.value = false
    cart.value = []
    await reloadGroups()
    activeGid.value = r.id
  } finally {
    creating.value = false
  }
}

// ── 加入已有分组 ──
const addVisible = ref(false)
const addTargetGid = ref('')
const addDate = ref('')
const adding = ref(false)
function openAddTo() {
  if (!cartCodes.value.length) return ElMessage.warning('请先勾选股票')
  addTargetGid.value = groups.value[0]?.id ?? ''
  addDate.value = dataMax.value || ''
  addVisible.value = true
}
async function doAddTo() {
  if (!addTargetGid.value) return ElMessage.warning('请选择目标分组')
  adding.value = true
  try {
    const r = await addMembers(addTargetGid.value, cartCodes.value, addDate.value || undefined)
    ElMessage.success(`已加入 ${r.added} 只`)
    addVisible.value = false
    cart.value = []
    await reloadGroups()
    if (activeGid.value === addTargetGid.value) await loadGroupDetail()
  } finally {
    adding.value = false
  }
}

// ── 从分组移出 ──
async function removeFromGroup() {
  if (!inGroupMode.value || !cartCodes.value.length) return
  await removeMembers(activeGid.value, cartCodes.value)
  ElMessage.success(`已移出 ${cartCodes.value.length} 只`)
  cart.value = []
  await Promise.all([reloadGroups(), loadGroupDetail()])
}

// ── 编辑 / 删除分组 ──
const editVisible = ref(false)
const editForm = ref<{ name: string; group_date: string; description: string }>({ name: '', group_date: '', description: '' })
function openEdit() {
  if (!groupDetail.value) return
  editForm.value = { name: groupDetail.value.name, group_date: groupDetail.value.group_date || '', description: groupDetail.value.description || '' }
  editVisible.value = true
}
async function doEdit() {
  await updateGroup(activeGid.value, {
    name: editForm.value.name.trim(),
    group_date: editForm.value.group_date || undefined,
    description: editForm.value.description,
  })
  ElMessage.success('已更新')
  editVisible.value = false
  await Promise.all([reloadGroups(), loadGroupDetail()])
}
async function doDeleteGroup() {
  if (!groupDetail.value) return
  await ElMessageBox.confirm(`确认删除分组「${groupDetail.value.name}」？成员关系一并清除。`, '删除分组', { type: 'warning' })
  await deleteGroup(activeGid.value)
  ElMessage.success('已删除')
  activeGid.value = ''
  await reloadGroups()
}

onMounted(async () => {
  await Promise.all([load(), reloadGroups()])
})
</script>

<template>
  <div class="v-page">
    <div class="page-head">
      <h2>个股查询</h2>
      <el-select v-model="activeGid" placeholder="查看分组" clearable filterable style="width: 200px">
        <el-option v-for="g in groups" :key="g.id" :value="g.id" :label="`${g.name}（${g.member_count}）`" />
      </el-select>
    </div>

    <!-- 搜索 / 筛选（置顶）-->
    <el-card v-if="!inGroupMode" shadow="never" class="filter-card">
      <div class="filter-row">
        <TradeDatePicker v-model="tradeDate" placeholder="交易日期(默认最新)" clearable style="width: 180px" />
        <el-input v-model="q" placeholder="代码 / 名称" style="width: 220px" clearable @keyup.enter="search" @clear="search" />
        <el-select v-model="board" placeholder="全部板块" style="width: 130px" clearable @change="search">
          <el-option label="主板" value="主板" />
          <el-option label="创业板" value="创业板" />
          <el-option label="科创板" value="科创板" />
          <el-option label="ST 板块" value="ST" />
          <el-option label="退市板块" value="退市" />
        </el-select>
        <el-checkbox v-if="board !== 'ST' && board !== '退市'" v-model="excludeSt" @change="search">排除 ST</el-checkbox>
        <el-button type="primary" :loading="loading" @click="search">查询</el-button>
      </div>
    </el-card>

    <!-- 分组横幅 -->
    <el-card v-if="inGroupMode && groupDetail" shadow="never" class="group-banner">
      <div class="gb-row">
        <div class="gb-main">
          <span class="gb-name">{{ groupDetail.name }}</span>
          <el-tag size="small" effect="plain">建组 {{ groupDetail.group_date || '—' }}</el-tag>
          <el-tag size="small" effect="plain">{{ groupDetail.count }} 只</el-tag>
          <span class="gb-ret">整组涨幅
            <b :class="pctClass(groupDetail.avg_ret)">{{ fmtPctRatio(groupDetail.avg_ret) }}</b>
            <span class="gb-hint">（各股自加入日起·等权平均）</span>
          </span>
        </div>
        <div class="gb-ops">
          <span v-if="groupDetail.description" class="gb-desc">{{ groupDetail.description }}</span>
          <el-button size="small" @click="openEdit">编辑</el-button>
          <el-button size="small" type="danger" plain @click="doDeleteGroup">删除分组</el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="v-grow">
      <!-- 分组视图 -->
      <el-table v-if="inGroupMode" :data="groupRows" v-loading="groupLoading" stripe row-key="code"
        height="100%"
        class="clickable" @row-click="(r: GroupMember) => enterDetail(r.code)">
        <el-table-column width="46">
          <template #header>
            <el-checkbox :model-value="allCurChecked" :indeterminate="someCurChecked" @change="toggleAllCur" />
          </template>
          <template #default="{ row }">
            <span @click.stop><el-checkbox :model-value="inCart(row.code)" @change="() => toggle(row)" /></span>
          </template>
        </el-table-column>
        <el-table-column label="代码" prop="code" width="120" />
        <el-table-column label="名称" prop="name" min-width="120">
          <template #default="{ row }">{{ row.name || '—' }}</template>
        </el-table-column>
        <el-table-column label="加入日期" prop="add_date" width="120">
          <template #default="{ row }">{{ row.add_date || '—' }}</template>
        </el-table-column>
        <el-table-column label="最近涨幅" prop="ret" width="120" sortable>
          <template #default="{ row }"><b :class="pctClass(row.ret)">{{ fmtPctRatio(row.ret) }}</b></template>
        </el-table-column>
        <el-table-column label="截至" prop="last_date" width="120">
          <template #default="{ row }">{{ row.last_date || '—' }}</template>
        </el-table-column>
      </el-table>

      <!-- 普通查询 -->
      <template v-else>
        <el-table :data="rows" v-loading="loading" stripe row-key="code"
          height="100%"
          class="clickable" @row-click="(r: StockBasic) => enterDetail(r.code)"
          :default-sort="{ prop: 'pct_chg', order: 'ascending' }" @sort-change="onSortChange">
          <el-table-column width="46">
            <template #header>
              <el-checkbox :model-value="allCurChecked" :indeterminate="someCurChecked" @change="toggleAllCur" />
            </template>
            <template #default="{ row }">
              <span @click.stop><el-checkbox :model-value="inCart(row.code)" @change="() => toggle(row)" /></span>
            </template>
          </el-table-column>
          <el-table-column label="代码" prop="code" width="116" sortable="custom" />
          <el-table-column label="名称" prop="name" min-width="130" sortable="custom">
            <template #default="{ row }">
              <span>{{ row.name || '—' }}</span>
              <el-tag v-if="row.is_st" type="danger" size="small" effect="plain" style="margin-left:6px">ST</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="涨跌幅" prop="pct_chg" width="120" sortable="custom">
            <template #default="{ row }"><b :class="pctClass(row.pct_chg)">{{ fmtPct(row.pct_chg) }}</b></template>
          </el-table-column>
          <el-table-column label="行业" prop="industry" sortable="custom">
            <template #default="{ row }">{{ row.industry || '—' }}</template>
          </el-table-column>
          <el-table-column label="板块" prop="board" width="100" />
          <el-table-column label="状态" width="84">
            <template #default="{ row }">
              <el-tag v-if="row.delist_date" type="info" effect="plain" size="small">退市</el-tag>
              <el-tag v-else :type="row.is_st ? 'danger' : 'success'" effect="plain" size="small">
                {{ row.is_st ? 'ST' : '正常' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination layout="total, sizes, prev, pager, next" :total="total" :page-size="size"
            :page-sizes="[20, 50, 100, 200]" :current-page="page"
            @current-change="(p:number)=>{ page=p; load() }"
            @size-change="(s:number)=>{ size=s; page=1; load() }" />
        </div>
      </template>
    </el-card>

    <!-- 操作区：列表后面（非固定）。选择跨分页/跨搜索累积 -->
    <el-card v-if="cart.length" shadow="never" class="cart-card">
      <div class="cart-row">
        <div class="cart-info">
          <span class="cart-n">已选 <b>{{ cart.length }}</b> 只</span>
          <div class="chips">
            <el-tag v-for="c in cart.slice(0, 30)" :key="c.code" size="small" closable @close="toggle(c)" class="chip">
              {{ c.name || c.code }}
            </el-tag>
            <span v-if="cart.length > 30" class="more">… 等 {{ cart.length }} 只</span>
          </div>
        </div>
        <div class="cart-ops">
          <el-button size="small" type="primary" @click="viewCartOneByOne">逐个查看</el-button>
          <template v-if="inGroupMode">
            <el-button size="small" type="danger" plain @click="removeFromGroup">从本组移出</el-button>
          </template>
          <template v-else>
            <el-button size="small" @click="openCreate">存为新分组</el-button>
            <el-button size="small" @click="openAddTo">加入已有分组</el-button>
          </template>
          <el-button size="small" text @click="cart = []">清空</el-button>
        </div>
      </div>
    </el-card>

    <!-- 存为新分组 -->
    <el-dialog v-model="createVisible" title="存为新分组" width="460px">
      <el-form label-width="80px">
        <el-form-item label="分组名">
          <el-input v-model="createForm.name" placeholder="如：5月观察龙头" maxlength="30" show-word-limit />
        </el-form-item>
        <el-form-item label="建组日期">
          <TradeDatePicker v-model="createForm.group_date" placeholder="默认最新交易日" clearable style="width: 200px" />
          <span class="f-hint">这批股票加入日期默认 = 建组日期（涨幅基准）</span>
        </el-form-item>
        <el-form-item label="分组说明">
          <el-input v-model="createForm.description" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
      </el-form>
      <div class="f-codes">将加入 {{ cartCodes.length }} 只：{{ cart.slice(0, 8).map(c => c.name || c.code).join('、') }}{{ cart.length > 8 ? ' …' : '' }}</div>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="doCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 加入已有分组 -->
    <el-dialog v-model="addVisible" title="加入已有分组" width="440px">
      <el-form label-width="80px">
        <el-form-item label="目标分组">
          <el-select v-model="addTargetGid" filterable style="width: 100%">
            <el-option v-for="g in groups" :key="g.id" :value="g.id" :label="`${g.name}（${g.member_count}）`" />
          </el-select>
        </el-form-item>
        <el-form-item label="加入日期">
          <TradeDatePicker v-model="addDate" placeholder="默认最新交易日" clearable style="width: 200px" />
          <span class="f-hint">作为这批股票的涨幅基准</span>
        </el-form-item>
      </el-form>
      <div class="f-codes">将加入 {{ cartCodes.length }} 只（已在组内的保留原加入日期）</div>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="doAddTo">加入</el-button>
      </template>
    </el-dialog>

    <!-- 编辑分组 -->
    <el-dialog v-model="editVisible" title="编辑分组" width="460px">
      <el-form label-width="80px">
        <el-form-item label="分组名"><el-input v-model="editForm.name" maxlength="30" show-word-limit /></el-form-item>
        <el-form-item label="建组日期"><TradeDatePicker v-model="editForm.group_date" clearable style="width: 200px" /></el-form-item>
        <el-form-item label="分组说明"><el-input v-model="editForm.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="doEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  gap: 12px;
  flex-wrap: wrap;
}
.page-head h2 {
  margin: 0;
  font-size: 20px;
}
.filter-card {
  margin-bottom: 12px;
}
.filter-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.group-banner {
  margin-bottom: 12px;
}
.gb-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.gb-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.gb-name {
  font-size: 16px;
  font-weight: 600;
}
.gb-ret {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.gb-ret b {
  font-size: 16px;
  margin: 0 2px;
}
.gb-hint,
.f-hint {
  color: #909399;
  font-size: 12px;
}
.gb-ops {
  display: flex;
  align-items: center;
  gap: 8px;
}
.gb-desc {
  color: #909399;
  font-size: 12px;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.up {
  color: #f56c6c;
}
.down {
  color: #2e9e5b;
}
.muted {
  color: #c0c4cc;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.clickable :deep(.el-table__row) {
  cursor: pointer;
}
.cart-card {
  margin-top: 14px;
  border: 1px solid var(--el-color-primary-light-7);
}
.cart-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}
.cart-info {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex: 1;
  min-width: 260px;
}
.cart-n {
  font-size: 13px;
  white-space: nowrap;
  padding-top: 2px;
}
.cart-n b {
  color: #f56c6c;
  font-size: 16px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  cursor: default;
}
.more {
  color: #909399;
  font-size: 12px;
  align-self: center;
}
.cart-ops {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}
.f-codes {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 4px;
}
</style>
