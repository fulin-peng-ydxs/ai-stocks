<script setup lang="ts">
// 统一「资产搜索抽屉」（R5/R7/R14）：系统内置/租户公开/全体公开三来源分段 + 防抖关键字 +
// 服务端分页 + 四态；操作列「加载查看 / 复制为我的」（回测为「加载查看 / 复用参数重跑」）。
// 取数与复制通过回调注入，评分/筛选/买卖/榜单/个股详情/回测共用本组件（原型 §7.1）。
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import PageDrawer from '@/components/PageDrawer.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppPagination from '@/components/AppPagination.vue'
import AssetProfileLabel from '@/components/AssetProfileLabel.vue'
import AssetVisibilityTag from '@/components/AssetVisibilityTag.vue'
import type { AppRowAction } from '@/components/rowActions'
import { getErrorMessage } from '@/utils/error'
import {
  assetItemKey,
  formatAssetTime,
  isProfileSummary,
  type AssetBrowseItem,
  type AssetBrowseParams,
  type AssetBrowseResult,
  type AssetBrowseSource,
  type AssetCopyResult,
  type BacktestRunSummary,
  type ProfileSummary,
} from './types'

const props = withDefaults(defineProps<{
  modelValue: boolean
  /** 资产中文名，例「筛选方案」→ 标题「浏览筛选方案」、空态「暂无{来源}筛选方案」 */
  assetLabel: string
  /** 列与操作模型：方案类（含系统内置段 + 复制）/ 回测（无系统内置段，复用参数重跑） */
  kind?: 'profile' | 'backtest'
  browse: (params: AssetBrowseParams) => Promise<AssetBrowseResult>
  copyItem?: (item: AssetBrowseItem) => Promise<AssetCopyResult>
  copyPermission?: string
  rerunItem?: (item: AssetBrowseItem) => Promise<unknown>
  rerunPermission?: string
  /** 是否具备浏览（查看）权限；false 时显示无权态、不调 browse（DESIGN 权限态，§307） */
  canBrowse?: boolean
  testId?: string
}>(), {
  kind: 'profile',
  copyItem: undefined,
  copyPermission: '',
  rerunItem: undefined,
  rerunPermission: '',
  canBrowse: true,
  testId: 'asset-search-drawer',
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  /** 加载查看：临时只读注入，由父级关闭抽屉后注入选择器（§7.0 契约） */
  load: [item: AssetBrowseItem]
  copied: [result: AssetCopyResult, item: AssetBrowseItem]
  rerunDone: [item: AssetBrowseItem]
}>()

const SOURCE_LABEL: Record<AssetBrowseSource, string> = {
  preset: '系统内置',
  tenant: '租户公开',
  public: '全体公开',
}

const segments = computed(() => (
  props.kind === 'profile'
    ? (['preset', 'tenant', 'public'] as AssetBrowseSource[])
    : (['tenant', 'public'] as AssetBrowseSource[])
).map((value) => ({ label: SOURCE_LABEL[value], value })))

const defaultSource = computed<AssetBrowseSource>(() => (props.kind === 'profile' ? 'preset' : 'public'))

const source = ref<AssetBrowseSource>(defaultSource.value)
const q = ref('')
const page = ref(1)
const pageSize = ref(20)
const items = ref<AssetBrowseItem[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const copyingKey = ref('')
const rerunningKey = ref('')
let fetchSeq = 0
let searchTimer: ReturnType<typeof setTimeout> | null = null

const open = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

async function fetchPage() {
  if (!props.canBrowse) return
  const seq = ++fetchSeq
  loading.value = true
  error.value = ''
  try {
    const result = await props.browse({
      source: source.value,
      q: q.value.trim(),
      page: page.value,
      pageSize: pageSize.value,
    })
    if (seq !== fetchSeq) return
    items.value = result.items
    total.value = result.total
    page.value = result.page
  } catch (err) {
    if (seq !== fetchSeq) return
    items.value = []
    total.value = 0
    error.value = getErrorMessage(err, `${props.assetLabel}加载失败`)
  } finally {
    if (seq === fetchSeq) loading.value = false
  }
}

// 打开时重置为默认来源段与空关键字；openWith 可指定起始段（空态引导「系统内置」）。
// syncing 抑制重置期间 source/q watcher 的重复拉取（flush:sync 保证即时生效）。
let pendingSource: AssetBrowseSource | null = null
let syncing = false

// 关闭/卸载时清理防抖计时器，并递增 fetchSeq 使在途响应失效（避免隐藏请求与重复查询）
function clearSearchTimer() {
  if (searchTimer) {
    clearTimeout(searchTimer)
    searchTimer = null
  }
}
watch(open, (value) => {
  if (!value) {
    clearSearchTimer()
    fetchSeq += 1
    return
  }
  syncing = true
  source.value = pendingSource ?? defaultSource.value
  pendingSource = null
  q.value = ''
  page.value = 1
  syncing = false
  void fetchPage()
}, { flush: 'sync', immediate: true })

watch(source, () => {
  if (syncing || !open.value) return
  page.value = 1
  void fetchPage()
}, { flush: 'sync' })

watch(q, () => {
  if (syncing || !open.value) return
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    searchTimer = null
    page.value = 1
    void fetchPage()
  }, 300)
}, { flush: 'sync' })

function openWith(next?: AssetBrowseSource) {
  pendingSource = next ?? null
  open.value = true
  if (pendingSource != null) {
    // 抽屉本就已打开时 open watcher 不触发，就地重置
    syncing = true
    source.value = pendingSource
    pendingSource = null
    q.value = ''
    page.value = 1
    syncing = false
    void fetchPage()
  }
}

defineExpose({ openWith })

onBeforeUnmount(() => {
  clearSearchTimer()
  fetchSeq += 1
})

function onPageChange(value: number) {
  page.value = value
  void fetchPage()
}
function onSizeChange(value: number) {
  pageSize.value = value
  page.value = 1
  void fetchPage()
}

function onLoad(item: AssetBrowseItem) {
  emit('load', item)
  open.value = false
}

async function onCopy(item: AssetBrowseItem) {
  if (!props.copyItem || copyingKey.value) return
  const key = assetItemKey(item)
  copyingKey.value = key
  try {
    const result = await props.copyItem(item)
    ElMessage.success(`已复制为「我的${props.assetLabel}」（名称「${result.name || '原名 副本'}」）`)
    emit('copied', result, item)
  } catch {
    // 全局响应拦截已 toast；此处只复位行内 loading
  } finally {
    copyingKey.value = ''
  }
}

async function onRerun(item: AssetBrowseItem) {
  if (!props.rerunItem || rerunningKey.value) return
  const key = assetItemKey(item)
  rerunningKey.value = key
  try {
    await props.rerunItem(item)
    emit('rerunDone', item)
  } catch {
    // 全局响应拦截已 toast；此处只复位行内 loading
  } finally {
    rerunningKey.value = ''
  }
}

function rowActions(item: AssetBrowseItem): AppRowAction[] {
  const key = assetItemKey(item)
  const actions: AppRowAction[] = [
    {
      key: 'load',
      label: '加载查看',
      testId: `${props.testId}-load`,
      onClick: () => onLoad(item),
    },
  ]
  if (props.kind === 'backtest') {
    if (props.rerunItem) {
      actions.push({
        key: 'rerun',
        label: '复用参数重跑',
        testId: `${props.testId}-rerun`,
        permission: props.rerunPermission || undefined,
        loading: rerunningKey.value === key,
        onClick: () => void onRerun(item),
      })
    }
    return actions
  }
  if (props.copyItem) {
    actions.push({
      key: 'copy',
      label: '复制为我的',
      testId: `${props.testId}-copy`,
      permission: props.copyPermission || undefined,
      loading: copyingKey.value === key,
      onClick: () => void onCopy(item),
    })
  }
  return actions
}

const emptyText = computed(() => `暂无${SOURCE_LABEL[source.value]}${props.assetLabel}`)
const searchPlaceholder = computed(() => (
  props.kind === 'backtest'
    ? '按引用方案名/回测类型搜索（留空显示该来源全部）'
    : `按${props.assetLabel}名称搜索（留空显示该来源全部）`
))

function profileOf(item: AssetBrowseItem): ProfileSummary | null {
  return isProfileSummary(item) ? item : null
}
function backtestOf(item: AssetBrowseItem): BacktestRunSummary | null {
  return isProfileSummary(item) ? null : (item as BacktestRunSummary)
}
</script>

<template>
  <PageDrawer v-model="open" size="xl" :title="`浏览${assetLabel}`" class="asset-search-drawer">
    <div class="asset-search" :data-testid="testId">
      <div v-if="canBrowse" class="asset-search__toolbar">
        <PageSegmented
          v-model="source"
          :options="segments"
          :test-id="`${testId}-segment`"
          aria-label="资产来源"
        />
        <el-input
          v-model="q"
          class="asset-search__q"
          clearable
          :placeholder="searchPlaceholder"
          :data-testid="`${testId}-q`"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
      </div>

      <div class="asset-search__body">
        <AppStateBlock
          v-if="!canBrowse"
          state="error"
          variant="permission"
          :title="`无权限查看${assetLabel}`"
          description="请联系系统管理员调整权限"
        />
        <AppStateBlock
          v-else-if="error"
          state="error"
          :title="`${assetLabel}加载失败`"
          :description="error"
          retry
          @retry="fetchPage"
        />
        <AppDataTable
          v-else
          embedded
          :data="items"
          :loading="loading"
          :row-key="(row: AssetBrowseItem) => assetItemKey(row)"
          :aria-label="`浏览${assetLabel}`"
        >
          <template v-if="kind === 'profile'">
            <!-- 方案类列契约（合并形态）：方案名称(名称+版本/更新时间次行)/来源(徽标 title 含提供者)/操作 -->
            <AppTableColumn label="方案名称" prop="name">
              <template #default="{ row }">
                <div v-if="profileOf(row)" class="asset-search__profile">
                  <AssetProfileLabel
                    :name="profileOf(row)!.name"
                    :version="profileOf(row)!.version"
                    :readonly="profileOf(row)!.readonly"
                  />
                  <span class="asset-search__profile-meta app-caption-text">
                    更新于 {{ formatAssetTime(profileOf(row)?.updated_at) }}
                  </span>
                </div>
              </template>
            </AppTableColumn>
            <AppTableColumn label="来源">
              <template #default="{ row }">
                <AssetVisibilityTag
                  v-if="profileOf(row)"
                  mode="source"
                  :source="profileOf(row)!.is_preset ? 'preset' : profileOf(row)!.source"
                  :owner-label="profileOf(row)!.owner_label"
                  :readonly="profileOf(row)!.readonly"
                />
              </template>
            </AppTableColumn>
          </template>

          <template v-else>
            <AppTableColumn label="回测" role="name">
              <template #default="{ row }">
                <template v-if="backtestOf(row)">
                  <span class="asset-search__run app-data-text">
                    {{ backtestOf(row)!.kind || '回测' }}
                    <span class="asset-search__run-range app-caption-text">
                      {{ backtestOf(row)!.date_start || '—' }} ~ {{ backtestOf(row)!.date_end || '—' }}
                    </span>
                  </span>
                </template>
              </template>
            </AppTableColumn>
            <AppTableColumn label="状态" prop="status">
              <template #default="{ row }">
                {{ backtestOf(row)?.status || '—' }}
              </template>
            </AppTableColumn>
            <AppTableColumn label="来源">
              <template #default="{ row }">
                <AssetVisibilityTag
                  mode="source"
                  :source="backtestOf(row)?.source"
                  :owner-label="backtestOf(row)?.owner_label"
                  :readonly="backtestOf(row)?.readonly"
                />
              </template>
            </AppTableColumn>
            <AppTableColumn label="提供者">
              <template #default="{ row }">
                {{ backtestOf(row)?.owner_label || '—' }}
              </template>
            </AppTableColumn>
            <AppTableColumn label="创建时间">
              <template #default="{ row }">
                {{ formatAssetTime(backtestOf(row)?.created_at) }}
              </template>
            </AppTableColumn>
          </template>

          <AppTableColumn label="操作" role="action" fixed="right">
            <template #default="{ row }">
              <AppRowActions :actions="rowActions(row)" :aria-label="`${assetLabel}行操作`" />
            </template>
          </AppTableColumn>

          <template #empty>
            <span>{{ emptyText }}</span>
          </template>
        </AppDataTable>
      </div>

      <div v-if="canBrowse" class="asset-search__footer">
        <span class="asset-search__count app-caption-text">共 {{ total }} 条{{ SOURCE_LABEL[source] }}{{ assetLabel }}</span>
        <AppPagination
          :current-page="page"
          :page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          small
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>
    </div>
  </PageDrawer>
</template>

<style scoped>
.asset-search {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  height: 100%;
  min-height: 0;
}
.asset-search__toolbar {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
}
.asset-search__toolbar :deep(.page-segmented) {
  flex: 0 0 auto;
}
.asset-search__q {
  flex: 1 1 200px;
  min-width: 0;
}
.asset-search__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}
.asset-search__footer {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-2);
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: var(--app-space-2);
}
.asset-search__count {
  color: var(--el-text-color-secondary);
}
.asset-search__run {
  display: inline-flex;
  flex-direction: column;
  line-height: var(--app-line-height-compact);
}
.asset-search__profile {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: var(--app-line-height-compact);
}
.asset-search__profile-meta {
  color: var(--el-text-color-secondary);
  margin-top: var(--app-space-1);
}
.asset-search__run-range {
  color: var(--el-text-color-secondary);
}
</style>
