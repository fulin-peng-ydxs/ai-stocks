<script setup lang="ts">
// 统一「资产方案选择器」（R3/R7）：下拉/侧栏双形态，列表只加载「我的」资产（纯 owner），
// 内置「搜索」入口打开 AssetSearchDrawer；「加载查看」注入会话内临时只读选中项
// （不进「我的」、切换即丢弃、不持久化、不自动运行，§7.0 契约）；「复制为我的」
// 成功后刷新「我的」并选中新资产。五页选择器实例统一消费本组件，不允许页面私有同类逻辑。
// 权限态（§307）：配置 viewPermission 后，无权限角色不渲染搜索入口与复制引导，
// 不调用 browse（避免 403），抽屉内显示「无权限查看」无权态——不把无权伪装成空态。
import { computed, onMounted, ref, watch } from 'vue'
import { Search } from '@element-plus/icons-vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AssetProfileLabel from '@/components/AssetProfileLabel.vue'
import AssetSearchDrawer from './AssetSearchDrawer.vue'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/utils/error'
import { hasPermission } from '@/utils/permission'
import {
  assetItemKey,
  assetDisplaySource,
  type AssetBrowseItem,
  type AssetBrowseParams,
  type AssetBrowseResult,
  type AssetBrowseSource,
  type AssetCopyResult,
  type ProfileSummary,
} from './types'

const props = withDefaults(defineProps<{
  modelValue: string
  /** select=下拉形态（筛选/榜单/个股详情/回测）；list=侧栏列表形态（配置页） */
  mode?: 'select' | 'list'
  /** 资产中文名，例「筛选方案」 */
  assetLabel: string
  fetchMine: () => Promise<ProfileSummary[]>
  browse: (params: AssetBrowseParams) => Promise<AssetBrowseResult>
  copyItem: (item: ProfileSummary) => Promise<AssetCopyResult>
  copyPermission?: string
  /** 查看（browse）权限码；传入且无权限时不渲染搜索入口与复制引导，抽屉显示无权态（DESIGN 权限态，§307） */
  viewPermission?: string
  placeholder?: string
  labelMine?: string
  testId?: string
  /** 加载查看后直接选中：适用于“选择即执行/展示”的消费页；默认仍只发 loaded，由页面决定展示方式。 */
  selectLoaded?: boolean
}>(), {
  mode: 'select',
  copyPermission: '',
  viewPermission: '',
  placeholder: '',
  labelMine: '我的方案',
  testId: 'asset-profile-select',
  selectLoaded: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  /** 临时只读对象注入（加载查看）；父级据此拉详情/展示，不自动运行。不再联动 update:modelValue，是否设为当前选中由父级决定 */
  loaded: [item: ProfileSummary]
  /** 列表加载完成（含 onMounted 首次与复制后刷新）；组件为列表唯一事实源，父级经此接收，不再重复 fetch */
  ready: [items: ProfileSummary[]]
  /** 列表加载失败；需要首屏汇合的父级据此结束 pending 并展示可重试错误态。 */
  loadFailed: [message: string]
  /** 复制成功且列表已刷新：回写完整 summary（含 source/readonly/is_preset），父级据此并入自身状态 */
  copiedItem: [item: ProfileSummary]
  /** 复制成功：列表已刷新、新资产已选中 */
  copied: [result: AssetCopyResult]
  /** 复用重跑完成（回测形态）：透传抽屉 rerunDone，回传 rerunItem 返回值 + 原行，供父级选中新 run */
  rerunDone: [result: unknown, item: ProfileSummary]
}>()

const items = ref<ProfileSummary[]>([])
// §7.0 会话内临时只读选中项：注入候选顶部，不进「我的」，切换即丢弃
const tempItem = ref<ProfileSummary | null>(null)
// 选择即执行页面的稳定只读 option：与 tempItem 分开，避免 ElSelect 把当前选中锁到临时预览项后递归更新。
const selectedLoadedItem = ref<ProfileSummary | null>(null)
const loadingMine = ref(false)
const errorMine = ref('')
const drawerOpen = ref(false)
const drawerRef = ref<InstanceType<typeof AssetSearchDrawer> | null>(null)
const auth = useAuthStore()

// 是否可打开搜索抽屉浏览公开资产；未配置 viewPermission 时默认可浏览
const canBrowse = computed(() => (
  !props.viewPermission || hasPermission(auth.role, auth.permissions, props.viewPermission)
))

const options = computed<ProfileSummary[]>(() => (
  selectedLoadedItem.value
    ? [selectedLoadedItem.value, ...items.value]
    : tempItem.value ? [tempItem.value, ...items.value] : items.value
))

const selectedItem = computed(() => (
  options.value.find((p) => assetItemKey(p) === props.modelValue) ?? null
))

const inner = computed({
  get: () => props.modelValue,
  set: (value: string) => emit('update:modelValue', value),
})

// 切换/清空选中即丢弃临时只读项
watch(() => props.modelValue, (value) => {
  if (tempItem.value && assetItemKey(tempItem.value) !== value) tempItem.value = null
  if (selectedLoadedItem.value && assetItemKey(selectedLoadedItem.value) !== value) selectedLoadedItem.value = null
})

async function reload(): Promise<ProfileSummary[]> {
  loadingMine.value = true
  errorMine.value = ''
  try {
    items.value = await props.fetchMine()
    emit('ready', items.value)
  } catch (error) {
    items.value = []
    errorMine.value = getErrorMessage(error, `${props.assetLabel}加载失败`)
    emit('loadFailed', errorMine.value)
  } finally {
    loadingMine.value = false
  }
  return items.value
}

onMounted(() => {
  void reload()
})

function openSearch(source?: AssetBrowseSource) {
  drawerRef.value?.openWith(source)
}

defineExpose({ reload, openSearch })

// 「加载查看」= 临时只读预览对象：注入候选顶部 + emit loaded，**不设为当前选中**（不 emit update:modelValue）。
// 关键：若同步选中，el-select 会把 selectedItem 锁到不在持久 items 的 tempItem 上，#label/option/watch 形成
// 稳定更新循环（ElSelect 递归超限）。故由各页 loaded 回调在**页面级状态**载入该对象做只读展示——
// ConfigView 编辑器 selectProfile 载入、个股详情 tradeId 回显，均不经过本组件的选中态。
function onDrawerLoad(raw: AssetBrowseItem) {
  const item = raw as ProfileSummary
  if (props.selectLoaded) {
    tempItem.value = null
    selectedLoadedItem.value = item
  } else {
    selectedLoadedItem.value = null
    tempItem.value = item
  }
  emit('loaded', item)
  if (props.selectLoaded) emit('update:modelValue', assetItemKey(item))
}

async function onDrawerCopied(result: AssetCopyResult) {
  const list = await reload()
  // 复制响应只含 id/profile_ref/name/version，回写完整 summary（含 source/readonly/is_preset）
  const copied = list.find((p) => p.id === result.id)
  if (copied) emit('copiedItem', copied)
  selectedLoadedItem.value = null
  tempItem.value = null
  emit('update:modelValue', result.profile_ref || result.id)
  emit('copied', result)
}

function onSelect(value: string) {
  emit('update:modelValue', value)
}

const emptyText = computed(() => `暂无我的${props.assetLabel}`)
</script>

<template>
  <div
    class="asset-profile-select"
    :class="`asset-profile-select--${mode}`"
    :data-testid="testId"
  >
    <template v-if="mode === 'select'">
      <el-select
        v-model="inner"
        class="asset-profile-select__select"
        :placeholder="placeholder || `选我的${assetLabel}（可选）`"
        clearable
        filterable
        :loading="loadingMine"
        :data-testid="`${testId}-select`"
      >
        <template v-if="selectedItem" #label>
          <AssetProfileLabel
            :name="selectedItem.name"
            :version="selectedItem.version"
            :source="assetDisplaySource(selectedItem.source, selectedItem.is_preset)"
            :is-preset="selectedItem.is_preset"
            :owner-label="selectedItem.owner_label"
            :readonly="selectedItem.readonly"
            :label-mine="labelMine"
          />
        </template>
        <el-option
          v-for="p in options"
          :key="assetItemKey(p)"
          :label="p.name"
          :value="assetItemKey(p)"
        >
          <AssetProfileLabel
            :name="p.name"
            :version="p.version"
            :source="assetDisplaySource(p.source, p.is_preset)"
            :is-preset="p.is_preset"
            :owner-label="p.owner_label"
            :readonly="p.readonly"
            :label-mine="labelMine"
          />
        </el-option>
        <template #empty>
          <div class="asset-profile-select__empty">
            <span>{{ emptyText }}</span>
            <el-button
              v-if="canBrowse"
              link
              type="primary"
              size="small"
              :data-testid="`${testId}-empty-search`"
              @click="openSearch('preset')"
            >
              去“系统内置”搜索复制
            </el-button>
          </div>
        </template>
      </el-select>
      <el-button
        v-if="canBrowse"
        class="asset-profile-select__search"
        :data-testid="`${testId}-search`"
        @click="openSearch()"
      >
        <template #icon>
          <el-icon><Search /></el-icon>
        </template>
        搜索
      </el-button>
    </template>

    <template v-else>
      <div v-if="canBrowse" class="asset-profile-select__list-head">
        <el-button
          class="asset-profile-select__search asset-profile-select__search--block"
          plain
          :data-testid="`${testId}-search`"
          @click="openSearch()"
        >
          <template #icon>
            <el-icon><Search /></el-icon>
          </template>
          搜索{{ assetLabel }}
        </el-button>
      </div>
      <ul v-if="options.length" class="asset-profile-select__list" v-loading="loadingMine">
        <li
          v-for="p in options"
          :key="assetItemKey(p)"
          :class="{ active: assetItemKey(p) === modelValue }"
          @click="onSelect(assetItemKey(p))"
        >
          <AssetProfileLabel
            :name="p.name"
            :version="p.version"
            :source="assetDisplaySource(p.source, p.is_preset)"
            :is-preset="p.is_preset"
            :owner-label="p.owner_label"
            :readonly="p.readonly"
            :label-mine="labelMine"
          />
        </li>
      </ul>
      <div v-else class="asset-profile-select__empty" v-loading="loadingMine">
        <span>{{ emptyText }}</span>
        <el-button
          v-if="canBrowse"
          link
          type="primary"
          size="small"
          :data-testid="`${testId}-empty-search`"
          @click="openSearch('preset')"
        >
          去“系统内置”搜索复制
        </el-button>
      </div>
    </template>

    <AppStateBlock
      v-if="errorMine"
      state="error"
      size="inline"
      :title="`${assetLabel}加载失败`"
      :description="errorMine"
      retry
      @retry="reload"
    />

    <AssetSearchDrawer
      ref="drawerRef"
      v-model="drawerOpen"
      :asset-label="assetLabel"
      kind="profile"
      :browse="browse"
      :copy-item="(item) => copyItem(item as ProfileSummary)"
      :copy-permission="copyPermission"
      :can-browse="canBrowse"
      @load="onDrawerLoad"
      @copied="onDrawerCopied"
    />
  </div>
</template>

<style scoped>
.asset-profile-select {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-2);
  min-width: 0;
}
.asset-profile-select--list {
  display: flex;
  flex-direction: column;
  align-items: stretch;
}
.asset-profile-select__select {
  flex: 1 1 auto;
  min-width: 0;
}
.asset-profile-select__search {
  flex: 0 0 auto;
}
.asset-profile-select__search--block {
  width: 100%;
}
.asset-profile-select__list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}
.asset-profile-select__list li {
  padding: 6px 8px;
  border-radius: var(--layout-control-radius, 6px);
  cursor: pointer;
}
.asset-profile-select__list li:hover {
  background: var(--el-fill-color-light);
}
.asset-profile-select__list li.active {
  background: var(--el-color-primary-light-9);
}
.asset-profile-select__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--app-space-1);
  padding: var(--app-space-3);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
</style>
