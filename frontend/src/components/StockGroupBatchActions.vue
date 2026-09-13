<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import {
  addMembers,
  createGroup,
  removeMembers,
  type GroupSummary,
} from '@/api/stockGroup'
import type { StockBatchItem } from '@/composables/useStockBatchSelection'
import {
  DEFAULT_STOCK_GROUP_COLOR,
  STOCK_GROUP_COLOR_PRESETS,
} from '@/utils/stockGroupPresentation'

const props = withDefaults(defineProps<{
  groups: GroupSummary[]
  defaultDate?: string
  mode?: 'assign' | 'remove'
  activeGroupId?: string
}>(), {
  defaultDate: '',
  mode: 'assign',
  activeGroupId: '',
})

const selected = defineModel<StockBatchItem[]>({ required: true })
const emit = defineEmits<{
  view: []
  changed: [groupId: string, action: 'create' | 'add' | 'remove']
}>()

const createVisible = ref(false)
const createForm = ref({
  name: '', group_date: '', description: '', color: DEFAULT_STOCK_GROUP_COLOR,
})
const creating = ref(false)
const addVisible = ref(false)
const addTargetGid = ref('')
const addDate = ref('')
const adding = ref(false)

function openCreate(): void {
  if (!selected.value.length) return
  createForm.value = {
    name: '', group_date: props.defaultDate, description: '', color: DEFAULT_STOCK_GROUP_COLOR,
  }
  createVisible.value = true
}

async function submitCreate(): Promise<void> {
  if (!createForm.value.name.trim()) {
    ElMessage.warning('请输入分组名')
    return
  }
  creating.value = true
  try {
    const result = await createGroup({
      name: createForm.value.name.trim(),
      group_date: createForm.value.group_date || undefined,
      description: createForm.value.description,
      color: createForm.value.color,
      codes: selected.value.map((item) => item.code),
    })
    ElMessage.success(`已创建分组（${selected.value.length} 只）`)
    createVisible.value = false
    selected.value = []
    emit('changed', result.id, 'create')
  } finally {
    creating.value = false
  }
}

function openAdd(): void {
  if (!selected.value.length) return
  addTargetGid.value = props.groups[0]?.id ?? ''
  addDate.value = props.defaultDate
  addVisible.value = true
}

async function submitAdd(): Promise<void> {
  if (!addTargetGid.value) {
    ElMessage.warning('请选择目标分组')
    return
  }
  adding.value = true
  try {
    const result = await addMembers(
      addTargetGid.value,
      selected.value.map((item) => item.code),
      addDate.value || undefined,
    )
    ElMessage.success(`已加入 ${result.added} 只`)
    const target = addTargetGid.value
    addVisible.value = false
    selected.value = []
    emit('changed', target, 'add')
  } finally {
    adding.value = false
  }
}

async function removeFromGroup(): Promise<void> {
  if (!props.activeGroupId || !selected.value.length) return
  const count = selected.value.length
  await removeMembers(props.activeGroupId, selected.value.map((item) => item.code))
  ElMessage.success(`已移出 ${count} 只`)
  const target = props.activeGroupId
  selected.value = []
  emit('changed', target, 'remove')
}
</script>

<template>
  <el-card v-if="selected.length" shadow="never" class="stock-batch-card">
    <div class="stock-batch-row">
      <div class="stock-batch-info">
        <span class="stock-batch-count">已选 <b>{{ selected.length }}</b> 只</span>
        <div class="stock-batch-chips">
          <el-tag
            v-for="item in selected.slice(0, 30)"
            :key="item.code"
            size="small"
            closable
            @close="selected = selected.filter((entry) => entry.code !== item.code)"
          >
            {{ item.name || item.code }}
          </el-tag>
          <span v-if="selected.length > 30" class="stock-batch-more">… 等 {{ selected.length }} 只</span>
        </div>
      </div>
      <div class="stock-batch-ops">
        <el-button size="small" type="primary" @click="emit('view')">逐个查看</el-button>
        <el-button
          v-if="mode === 'remove'"
          v-permission="'stock-group:member-update'"
          size="small"
          type="danger"
          plain
          @click="removeFromGroup"
        >从本组移出</el-button>
        <template v-else>
          <el-button v-permission="'stock-group:create'" size="small" @click="openCreate">存为新分组</el-button>
          <el-button v-permission="'stock-group:member-update'" size="small" @click="openAdd">加入已有分组</el-button>
        </template>
        <el-button size="small" text @click="selected = []">清空</el-button>
      </div>
    </div>
  </el-card>

  <el-dialog v-model="createVisible" title="存为新分组" width="460px">
    <el-form label-width="80px">
      <el-form-item label="分组名" required>
        <el-input v-model="createForm.name" placeholder="如：5月观察龙头" maxlength="30" show-word-limit />
      </el-form-item>
      <el-form-item label="建组日期">
        <TradeDatePicker v-model="createForm.group_date" placeholder="默认最新交易日" clearable style="width: 200px" />
        <span class="stock-batch-hint">这批股票加入日期默认 = 建组日期（涨幅基准）</span>
      </el-form-item>
      <el-form-item label="分组说明">
        <el-input v-model="createForm.description" type="textarea" :rows="2" placeholder="可选" />
      </el-form-item>
      <el-form-item label="颜色">
        <el-color-picker v-model="createForm.color" :predefine="STOCK_GROUP_COLOR_PRESETS" />
        <span class="stock-batch-hint">用于列表标签和分组状态识别</span>
      </el-form-item>
    </el-form>
    <div class="stock-batch-codes">
      将加入 {{ selected.length }} 只：{{ selected.slice(0, 8).map(item => item.name || item.code).join('、') }}{{ selected.length > 8 ? ' …' : '' }}
    </div>
    <template #footer>
      <el-button @click="createVisible = false">取消</el-button>
      <el-button v-permission="'stock-group:create'" type="primary" :loading="creating" @click="submitCreate">创建</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="addVisible" title="加入已有分组" width="440px">
    <el-form label-width="80px">
      <el-form-item label="目标分组" required>
        <el-select v-model="addTargetGid" filterable style="width: 100%">
          <el-option v-for="group in groups" :key="group.id" :value="group.id" :label="`${group.name}（${group.member_count}）`" />
        </el-select>
      </el-form-item>
      <el-form-item label="加入日期">
        <TradeDatePicker v-model="addDate" placeholder="默认最新交易日" clearable style="width: 200px" />
        <span class="stock-batch-hint">作为这批股票的涨幅基准</span>
      </el-form-item>
    </el-form>
    <div class="stock-batch-codes">将加入 {{ selected.length }} 只（已在组内的保留原加入日期）</div>
    <template #footer>
      <el-button @click="addVisible = false">取消</el-button>
      <el-button v-permission="'stock-group:member-update'" type="primary" :loading="adding" @click="submitAdd">加入</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.stock-batch-card { border: 1px solid var(--el-color-primary-light-7); flex: 0 0 auto; }
.stock-batch-row { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--app-space-4); flex-wrap: wrap; }
.stock-batch-info { display: flex; align-items: flex-start; gap: var(--app-space-3); flex: 1; min-width: 260px; }
.stock-batch-count { font-size: var(--app-font-size-table); white-space: nowrap; padding-top: 2px; }
.stock-batch-count b { color: var(--market-up-color); font-size: var(--app-font-size-data); }
.stock-batch-chips { display: flex; flex-wrap: wrap; gap: var(--app-space-control-gap); max-height: 64px; overflow: auto; }
.stock-batch-more, .stock-batch-hint { color: var(--app-muted-text); font-size: var(--app-font-size-caption); }
.stock-batch-more { align-self: center; }
.stock-batch-ops { display: flex; gap: var(--app-space-2); align-items: center; flex-shrink: 0; }
.stock-batch-codes { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); margin-top: 4px; }
</style>
