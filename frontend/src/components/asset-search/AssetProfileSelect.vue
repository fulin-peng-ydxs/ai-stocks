<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import AppIconButton from '@/components/AppIconButton.vue'
import AppScrollArea from '@/components/AppScrollArea.vue'
import { vKeyboardActivate } from '@/directives/keyboardActivate'
// 统一「资产方案选择器」（R3/R7）：下拉/侧栏双形态，列表只加载「我的」资产（纯 owner），
// 内置「搜索」入口打开 AssetSearchDrawer；「加载查看」注入会话内临时只读选中项
// （不进「我的」、切换即丢弃、不持久化、不自动运行，§7.0 契约）；「复制为我的」
// 成功后刷新「我的」并选中新资产。五页选择器实例统一消费本组件，不允许页面私有同类逻辑。
// 权限态（§307）：配置 viewPermission 后，无权限角色不渲染搜索入口与复制引导，
// 不调用 browse（避免 403），抽屉内显示「无权限查看」无权态——不把无权伪装成空态。
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { Search } from '@element-plus/icons-vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import AppCloseButton from '@/components/AppCloseButton.vue'
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
  /** 下拉旁搜索入口的呈现方式；图标形态沿用统一命令按钮。 */
  searchButton?: 'text' | 'icon'
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
  /** option=临时项注入本组件候选；external=仅通知父级，由父级在选择器外展示。 */
  loadedMode?: 'option' | 'external'
  /** 当前默认加载方案的资产 key（仅榜单页评分方案传）；透传给抽屉做行内互斥高亮 */
  defaultItemKey?: string
  /** list 形态给「加载查看」注入的临时项显示行内「×」：仅从列表移除该预览（不删数据、不碰我的方案） */
  removableTemp?: boolean
}>(), {
  mode: 'select',
  searchButton: 'text',
  copyPermission: '',
  viewPermission: '',
  placeholder: '',
  labelMine: '我的方案',
  testId: 'asset-profile-select',
  selectLoaded: false,
  loadedMode: 'option',
  defaultItemKey: undefined,
  removableTemp: true,
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
  /** 设为/取消默认加载方案（仅榜单页评分方案）：透传抽屉行操作，item=null 表示取消默认 */
  setDefault: [item: ProfileSummary | null]
  /** 行内「×」移除了「加载查看」临时预览项：只卸载预览、不删除资产；页面据此清掉编辑器身份/参数/结果 */
  tempRemoved: [item: ProfileSummary]
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
const selectRef = ref<{ blur: () => void } | null>(null)
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
const mineUnavailable = computed(() => !!errorMine.value && options.value.length === 0)

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

// 返回 mine 列表；失败时保留旧列表（不清空）并返回 null，由调用方区分成功/失败（P1-3）。
async function reload(): Promise<ProfileSummary[] | null> {
  loadingMine.value = true
  errorMine.value = ''
  try {
    items.value = await props.fetchMine()
    emit('ready', items.value)
    return items.value
  } catch (error) {
    // 保留旧列表：避免瞬时失败后选中项失去 summary 解析、显示 opaque ref
    errorMine.value = getErrorMessage(error, `${props.assetLabel}加载失败`)
    emit('loadFailed', errorMine.value)
    return null
  } finally {
    loadingMine.value = false
  }
}

onMounted(() => {
  void reload()
})

function openSearch(source?: AssetBrowseSource) {
  // 搜索入口可能位于 el-select 的空态浮层中。先结束选择器交互，再打开抽屉，
  // 避免 teleport 到页面容器的两个浮层同时可见、层级互相覆盖。
  if (selectRef.value) {
    selectRef.value.blur()
    void nextTick(() => drawerRef.value?.openWith(source))
    return
  }
  drawerRef.value?.openWith(source)
}

// 命令式装载（不进抽屉）：与 onDrawerLoad 的 selectLoaded 分支同构，供榜单页「默认加载方案」
// 在页面进入时复用已验证的 selectedLoadedItem 链路（选中项始终在 options 内，规避 ElSelect 递归陷阱）。
function applyLoaded(item: ProfileSummary) {
  if (!props.selectLoaded) return
  tempItem.value = null
  selectedLoadedItem.value = item
  emit('loaded', item)
  emit('update:modelValue', assetItemKey(item))
}

/** 清理所有会话内加载项；父级移除外部快照时用同一入口同步组件内部状态。 */
function clearTransient() {
  tempItem.value = null
  selectedLoadedItem.value = null
}

defineExpose({ reload, openSearch, applyLoaded, clearTransient })

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
    tempItem.value = props.loadedMode === 'option' ? item : null
  }
  emit('loaded', item)
  if (props.selectLoaded) emit('update:modelValue', assetItemKey(item))
}

async function onDrawerCopied(result: AssetCopyResult) {
  const list = await reload()
  // 复制响应只含 id/profile_ref/name/version，回写完整 summary（含 source/readonly/is_preset）
  const copied = list?.find((p) => p.id === result.id)
  if (copied) {
    emit('copiedItem', copied)
  } else {
    // 复制已成功但 mine 刷新失败，或刷新成功但新记录暂未出现在列表（P1-3/P2-2）：
    // 不写无法解析的裸 ref——用复制响应构造可解析的临时 mine summary 置顶进 items，
    // 让选中项始终有名称可显示（非 opaque ref），并 emit copiedItem 供父页同步临时快照。
    const fallback: ProfileSummary = {
      id: result.id,
      profile_ref: result.profile_ref,
      // name/version 已为必填（后端复制契约）；仍防 null/空串退化为 opaque ref，用中文兜底名
      name: result.name || `${props.assetLabel} 副本`,
      version: result.version || 1,
      is_preset: false,
      source: 'mine',
      readonly: false,
    }
    items.value = [fallback, ...items.value.filter((p) => p.id !== result.id)]
    emit('copiedItem', fallback)
  }
  selectedLoadedItem.value = null
  tempItem.value = null
  emit('update:modelValue', result.profile_ref || result.id)
  emit('copied', result)
}

function onSelect(value: string) {
  if (loadingMine.value) return
  emit('update:modelValue', value)
}

const emptyText = computed(() => `暂无我的${props.assetLabel}`)

// 行内「×」：仅给「加载查看」注入的临时预览项（tempItem，含系统内置/别人的非「我的」方案）显示；
// 仅从列表移除该预览、丢弃临时选中，不删数据、不调 API、不碰「我的」方案。
// 删除资产始终由消费页右上角的独立删除按钮承接，不得复用此入口。
function isTempRow(p: ProfileSummary): boolean {
  return props.removableTemp && !!tempItem.value && assetItemKey(p) === assetItemKey(tempItem.value)
}
function onRemoveTemp(p: ProfileSummary, event: MouseEvent) {
  event.stopPropagation()
  if (!isTempRow(p)) return
  // 若该预览项正是当前选中，先清空选中（watch 会随之丢弃 tempItem），再兜底复位。
  if (props.modelValue === assetItemKey(p)) inner.value = ''
  tempItem.value = null
  // 通知页面收尾：清掉该外来方案在编辑器的只读身份/运行口径，回到「我的」上下文
  emit('tempRemoved', p)
}
</script>

<template>
  <div
    class="asset-profile-select"
    :class="`asset-profile-select--${mode}`"
    :data-testid="testId"
  >
    <template v-if="mode === 'select'">
      <AppStateBlock
        v-if="mineUnavailable"
        class="asset-profile-select__state"
        state="error"
        size="inline"
        :title="`${assetLabel}加载失败`"
        :description="errorMine"
        retry
        @retry="reload"
      />
      <template v-else>
        <AppSelect
          ref="selectRef"
          v-model="inner"
          class="asset-profile-select__select"
          :placeholder="placeholder || `选我的${assetLabel}（可选）`"
          clearable
          filterable
          :loading="loadingMine"
          :data-testid="`${testId}-select`"
          popper-class="app-option-popper asset-profile-select-popper"
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
                text
                type="primary"
                size="small"
                :data-testid="`${testId}-empty-search`"
                @click="openSearch('preset')"
              >
                去“系统内置”搜索复制
              </el-button>
            </div>
          </template>
        </AppSelect>
        <AppIconButton
          v-if="canBrowse && searchButton === 'icon'"
          class="asset-profile-select__search"
          :label="`搜索${assetLabel}`"
          :data-testid="`${testId}-search`"
          @click="openSearch()"
        ><Search /></AppIconButton>
        <el-button
          v-else-if="canBrowse"
          class="asset-profile-select__search"
          :data-testid="`${testId}-search`"
          @click="openSearch()"
        >
          <template #icon>
            <el-icon><Search /></el-icon>
          </template>
          搜索
        </el-button>
        <AppStatusNotice
          v-if="errorMine"
          class="asset-profile-select__notice"
          tone="warning"
          size="inline"
          :title="`${assetLabel}暂未更新`"
          description="当前继续使用已加载的方案"
          action-text="重新加载"
          @action="reload"
        />
      </template>
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
      <AppStateBlock
        v-if="mineUnavailable"
        class="asset-profile-select__state"
        state="error"
        size="inline"
        :title="`${assetLabel}加载失败`"
        :description="errorMine"
        retry
        @retry="reload"
      />
      <template v-else-if="options.length">
        <AppStatusNotice
          v-if="errorMine"
          tone="warning"
          size="compact"
          :title="`${assetLabel}暂未更新`"
          description="当前继续使用已加载的方案"
          action-text="重新加载"
          @action="reload"
        />
        <AppScrollArea class="asset-profile-select__list-scroll"><ul class="asset-profile-select__list" v-loading="loadingMine">
          <li
            v-for="p in options"
            :key="assetItemKey(p)"
            class="asset-profile-select__item app-interaction-list-item app-interaction-list-item--outlined"
            :aria-busy="loadingMine"
            :class="{ active: assetItemKey(p) === modelValue }"
          >
            <AssetProfileLabel
              class="asset-profile-select__item-label app-list-item-trigger"
              role="button"
              :tabindex="loadingMine ? -1 : 0"
              :aria-disabled="loadingMine"
              :aria-pressed="assetItemKey(p) === modelValue"
              v-keyboard-activate
              @click="onSelect(assetItemKey(p))"
              :name="p.name"
              :version="p.version"
              :source="assetDisplaySource(p.source, p.is_preset)"
              :is-preset="p.is_preset"
              :owner-label="p.owner_label"
              :readonly="p.readonly"
              :label-mine="labelMine"
            />
            <AppCloseButton
              v-if="isTempRow(p)"
              class="asset-profile-select__remove"
              :label="`从列表移除「${p.name}」`"
              size="compact"
              :data-testid="`${testId}-remove`"
              @click="onRemoveTemp(p, $event)"
            />
          </li>
        </ul></AppScrollArea>
      </template>
      <div v-else class="asset-profile-select__empty">
        <AppStateBlock v-if="loadingMine" state="loading" size="tiny" :title="`正在加载${assetLabel}…`" />
        <template v-else>
          <span>{{ emptyText }}</span>
          <el-button
            v-if="canBrowse"
            text
            type="primary"
            size="small"
            :data-testid="`${testId}-empty-search`"
            @click="openSearch('preset')"
          >
            去“系统内置”搜索复制
          </el-button>
        </template>
      </div>
    </template>

    <AssetSearchDrawer
      ref="drawerRef"
      v-model="drawerOpen"
      :asset-label="assetLabel"
      kind="profile"
      :browse="browse"
      :copy-item="(item) => copyItem(item as ProfileSummary)"
      :copy-permission="copyPermission"
      :can-browse="canBrowse"
      :default-item-key="defaultItemKey"
      :set-default-item="defaultItemKey !== undefined ? (item) => emit('setDefault', (item as ProfileSummary | null)) : undefined"
      @load="onDrawerLoad"
      @copied="onDrawerCopied"
    />
  </div>
</template>

<style scoped>
:global(.asset-profile-select-popper .asset-profile-label) {
  width: 100%;
}
:global(.asset-profile-select-popper .asset-profile-label__name) {
  overflow: visible;
  text-overflow: clip;
  white-space: normal;
}
.asset-profile-select__list-scroll { max-height: inherit; }
.asset-profile-select {
  display: inline-grid;
  grid-template-columns: minmax(0, 1fr) auto;
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
.asset-profile-select__notice {
  grid-column: 1 / -1;
}
.asset-profile-select__state {
  grid-column: 1 / -1;
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
.asset-profile-select__item {
  display: flex;
  align-items: center;
  gap: var(--app-space-1);
  padding: 0;
  border-radius: var(--layout-control-radius, 6px);
  cursor: pointer;
}
.asset-profile-select__item-label {
  padding: 6px 8px;
  flex: 1 1 auto;
  min-width: 0;
}

/* 行内「×」：给「加载查看」临时预览项靠右放置，仅从列表移除预览（不删数据），用中性色区别于破坏性删除 */
.asset-profile-select__remove {
  flex: 0 0 auto;
  margin-left: auto;
  margin-right: 8px;
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
