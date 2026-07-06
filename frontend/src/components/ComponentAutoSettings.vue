<script setup lang="ts">
/**
 * 「组件特性」唯一渲染器——由 pageRegistry 的 consumedComponentFields + componentMeta 驱动，
 * 同时服务于**运行时页面设置抽屉**（user 层）与**页面布局编辑器**（page 层），各页不再手写
 * 列开关/排序/分页控件。每个被消费的 slot 渲染一个 SettingsGroup（level 2），内含：默认排序
 * （可排序字段 + 方向）、每页条数、列显隐（独立 level 3 子组，每列一个开关）等。
 * 写值统一经组件配置层（config.setComponentKnob），与配置中心/后端校验同源。
 *
 * 折叠规则（统一）：slot 是一个可折叠组；多行清单类特性（列显隐）作为可折叠子组；
 * 单字段为叶子不折叠。页面布局编辑器一次只聚焦一个 slot，slot 头作锚点不折叠（collapsibleSlot=false）。
 */
import { computed, nextTick, ref, watch } from 'vue'
import SettingsGroup from './SettingsGroup.vue'
import PageSegmented from './PageSegmented.vue'
import PageToggleRow from './PageToggleRow.vue'
import SourceTag from './SourceTag.vue'
import { getPageEntry, type SlotConfigMeta } from '@/layout/pageRegistry'
import { getComponentFieldDef, type ComponentConfigLayer, type ComponentConfigSource } from '@/layout/componentConfig'

interface ComponentConfigAccess {
  componentValueOf: (slotId: string, field: string) => unknown
  setComponentKnob: (slotId: string, field: string, value: unknown) => void
  /** 可选：读字段生效来源层，用于展示来源徽标（default/preset/page/user）。 */
  componentSourceOf?: (slotId: string, field: string) => ComponentConfigSource
  /** 可选：读字段逐层取值，用于来源 hover 展示。 */
  componentLayerValuesOf?: (slotId: string, field: string) => Partial<Record<ComponentConfigSource, unknown>>
}

const props = withDefaults(
  defineProps<{
    pageKey: string
    config: ComponentConfigAccess
    /** 编辑层：决定渲染哪些字段（按字段 layers + 开放策略门控）。抽屉=user，页面布局编辑器=page。 */
    layer?: ComponentConfigLayer
    /** 仅渲染这些 slot（页面布局编辑器聚焦单个 slot 时传）；缺省渲染全部被消费 slot（抽屉）。 */
    slotIds?: string[]
    /** 可选：「系统组件」开放策略当前生效层集合；返回 undefined 时回退 def.layers。 */
    allowedLayersOf?: (kind: string, field: string) => ComponentConfigLayer[] | undefined
    /** slot 级是否可折叠。抽屉(多 slot)为 true；页面布局编辑器(单 slot)为 false，仅作标题锚点。 */
    collapsibleSlot?: boolean
    /**
     * 是否渲染 slot 名作为分组标题。抽屉(多 slot)需要区分故为 true；页面布局编辑器聚焦单 slot、
     * 且外层已有 slot 卡片，置 false 去掉重复标题（此时内部「列显隐」升为 level 2）。
     */
    showSlotTitle?: boolean
    /** 可选：高亮并滚动到该 slot 组（页面布局「点击预览即配置」用）。 */
    highlightSlot?: string | null
    /** 可选：每个字段提供「不覆盖（清除）」入口（page 层编辑器用，清除即不在本层覆盖）。 */
    clearable?: boolean
    /** 页面没有业务设置 slot 时，隐藏设置抽屉的业务折叠段选项。 */
    drawerBusinessVisible?: boolean
  }>(),
  { layer: 'user', collapsibleSlot: true, showSlotTitle: true, clearable: false },
)

function srcOf(slotId: string, field: string): ComponentConfigSource | null {
  return props.config.componentSourceOf ? props.config.componentSourceOf(slotId, field) : null
}
function srcValuesOf(slotId: string, field: string) {
  return props.config.componentLayerValuesOf?.(slotId, field)
}

interface AutoSlot {
  slotId: string
  kind: string
  label: string
  fields: string[]
  meta: SlotConfigMeta
}

/** 字段是否允许在当前层覆盖（开放策略优先，回退 def.layers）。 */
function layerAllowed(kind: string, field: string): boolean {
  const def = getComponentFieldDef(kind as never, field)
  if (!def) return false
  return (props.allowedLayersOf?.(kind, field) ?? def.layers).includes(props.layer)
}

const autoSlots = computed<AutoSlot[]>(() => {
  const entry = getPageEntry(props.pageKey)
  if (!entry?.consumedComponentFields) return []
  const byId = new Map(entry.layout.slots.map((s) => [s.id, s]))
  const meta = entry.componentMeta ?? {}
  return Object.entries(entry.consumedComponentFields)
    .filter(([slotId]) => !props.slotIds || props.slotIds.includes(slotId))
    .map(([slotId, fields]) => {
      const slot = byId.get(slotId)
      return {
        slotId,
        kind: slot?.component ?? '',
        label: slot?.label || slotId,
        // 只渲染当前层（+策略）允许覆盖的字段；collapsibleSections 在 user 层天然被排除。
        fields: fields.filter((field) => layerAllowed(slot?.component ?? '', field)),
        meta: meta[slotId] ?? {},
      }
    })
    .filter((slot) => slot.fields.length)
})

// 高亮并滚动到聚焦 slot（页面布局「点击预览即配置」）。
const root = ref<HTMLElement | null>(null)
watch(
  () => props.highlightSlot,
  async (id) => {
    if (!id) return
    await nextTick()
    root.value?.querySelector(`[data-cc-slot="${id}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  },
)

const PAGE_SIZE_OPTIONS = [20, 50, 100, 200]
const ORDER_OPTIONS = [
  { label: '升序', value: 'asc' },
  { label: '降序', value: 'desc' },
]
const DRAWER_SECTION_OPTIONS = [
  { label: '布局', value: 'layout' },
  { label: '组件设置', value: 'components' },
  { label: '业务选项', value: 'business' },
]
const DRAWER_SIZE_OPTIONS = [
  { label: '小', value: 'sm' },
  { label: '中', value: 'md' },
  { label: '大', value: 'lg' },
]
const visibleDrawerSectionOptions = computed(() =>
  props.drawerBusinessVisible === false
    ? DRAWER_SECTION_OPTIONS.filter((option) => option.value !== 'business')
    : DRAWER_SECTION_OPTIONS,
)

function listVal(slotId: string, field: string): string[] {
  const v = props.config.componentValueOf(slotId, field)
  return Array.isArray(v) ? (v as string[]) : []
}
function strVal(slotId: string, field: string): string {
  const v = props.config.componentValueOf(slotId, field)
  return v == null ? '' : String(v)
}
function numVal(slotId: string, field: string, fallback: number): number {
  const v = props.config.componentValueOf(slotId, field)
  return typeof v === 'number' ? v : fallback
}
function boolVal(slotId: string, field: string, fallback: boolean): boolean {
  const v = props.config.componentValueOf(slotId, field)
  return typeof v === 'boolean' ? v : fallback
}

/** page 层「不覆盖」：清除本层显式值（null 视为不覆盖）。 */
function isOverridden(slotId: string, field: string): boolean {
  const v = props.config.componentValueOf(slotId, field)
  if (v == null || v === '') return false
  return Array.isArray(v) ? v.length > 0 : true
}
function clearField(slotId: string, field: string): void {
  props.config.setComponentKnob(slotId, field, null)
}

function colVisible(slotId: string, key: string): boolean {
  return !listVal(slotId, 'hiddenColumns').includes(key)
}
function setColVisible(slotId: string, key: string, visible: boolean): void {
  const set = new Set(listVal(slotId, 'hiddenColumns'))
  if (visible) set.delete(key)
  else set.add(key)
  props.config.setComponentKnob(slotId, 'hiddenColumns', [...set])
}

function sortField(slotId: string): string {
  return strVal(slotId, 'defaultSort').split(':')[0] ?? ''
}
function sortOrder(slotId: string): string {
  return strVal(slotId, 'defaultSort').split(':')[1] || 'desc'
}
function setSort(slotId: string, field: string, order: string): void {
  props.config.setComponentKnob(slotId, 'defaultSort', field ? `${field}:${order}` : '')
}
</script>

<template>
  <div v-if="autoSlots.length" ref="root">
    <SettingsGroup
      v-for="s in autoSlots"
      :key="s.slotId"
      :title="showSlotTitle ? s.label : undefined"
      :level="2"
      :collapsible="collapsibleSlot"
      :data-cc-slot="s.slotId"
      :class="{ 'ca-highlight': s.slotId === highlightSlot }"
    >
      <template v-if="s.fields.includes('defaultSort') && s.meta.sortFields?.length">
        <!-- field:order 模式：字段 + 方向 -->
        <div v-if="s.meta.sortHasDirection !== false" class="ca-item">
          <div class="ca-label-row">
            <span class="ca-label">默认排序字段</span>
            <span class="ca-actions">
              <SourceTag
                v-if="srcOf(s.slotId, 'defaultSort')"
                :source="srcOf(s.slotId, 'defaultSort')!"
                :values="srcValuesOf(s.slotId, 'defaultSort')"
              />
              <button v-if="clearable && isOverridden(s.slotId, 'defaultSort')" type="button" class="ca-clear" @click="clearField(s.slotId, 'defaultSort')">不覆盖</button>
            </span>
          </div>
          <PageSegmented
            :model-value="sortField(s.slotId)"
            :options="s.meta.sortFields.map((f) => ({ label: f.label, value: f.key }))"
            @update:model-value="(v) => setSort(s.slotId, String(v), sortOrder(s.slotId))"
          />
          <div class="ca-label">默认排序方向</div>
          <PageSegmented
            :model-value="sortOrder(s.slotId)"
            :options="ORDER_OPTIONS"
            @update:model-value="(v) => setSort(s.slotId, sortField(s.slotId), String(v))"
          />
        </div>
        <!-- 枚举模式：排序模式直接存 key（无方向，如 board 的 score/rank） -->
        <div v-else class="ca-item">
          <div class="ca-label-row">
            <span class="ca-label">默认排序</span>
            <span class="ca-actions">
              <SourceTag
                v-if="srcOf(s.slotId, 'defaultSort')"
                :source="srcOf(s.slotId, 'defaultSort')!"
                :values="srcValuesOf(s.slotId, 'defaultSort')"
              />
              <button v-if="clearable && isOverridden(s.slotId, 'defaultSort')" type="button" class="ca-clear" @click="clearField(s.slotId, 'defaultSort')">不覆盖</button>
            </span>
          </div>
          <PageSegmented
            :model-value="strVal(s.slotId, 'defaultSort')"
            :options="s.meta.sortFields.map((f) => ({ label: f.label, value: f.key }))"
            @update:model-value="(v) => config.setComponentKnob(s.slotId, 'defaultSort', String(v))"
          />
        </div>
      </template>

      <div v-if="s.fields.includes('pageSize')" class="ca-item">
        <div class="ca-label-row">
          <span class="ca-label">每页条数</span>
          <span class="ca-actions">
            <SourceTag
              v-if="srcOf(s.slotId, 'pageSize')"
              :source="srcOf(s.slotId, 'pageSize')!"
              :values="srcValuesOf(s.slotId, 'pageSize')"
            />
            <button v-if="clearable && isOverridden(s.slotId, 'pageSize')" type="button" class="ca-clear" @click="clearField(s.slotId, 'pageSize')">不覆盖</button>
          </span>
        </div>
        <PageSegmented
          :model-value="numVal(s.slotId, 'pageSize', 20)"
          :options="PAGE_SIZE_OPTIONS.map((n) => ({ label: String(n), value: n }))"
          @update:model-value="(v) => config.setComponentKnob(s.slotId, 'pageSize', Number(v))"
        />
      </div>

      <div v-if="s.fields.includes('defaultActive') && s.meta.tabs?.length" class="ca-item">
        <div class="ca-label-row">
          <span class="ca-label">默认标签页</span>
          <span class="ca-actions">
            <SourceTag
              v-if="srcOf(s.slotId, 'defaultActive')"
              :source="srcOf(s.slotId, 'defaultActive')!"
              :values="srcValuesOf(s.slotId, 'defaultActive')"
            />
            <button v-if="clearable && isOverridden(s.slotId, 'defaultActive')" type="button" class="ca-clear" @click="clearField(s.slotId, 'defaultActive')">不覆盖</button>
          </span>
        </div>
        <PageSegmented
          :model-value="strVal(s.slotId, 'defaultActive')"
          :options="s.meta.tabs.map((t) => ({ label: t.label, value: t.key }))"
          @update:model-value="(v) => config.setComponentKnob(s.slotId, 'defaultActive', String(v))"
        />
      </div>

      <div v-if="s.fields.includes('size')" class="ca-item">
        <div class="ca-label-row">
          <span class="ca-label">抽屉尺寸</span>
          <span class="ca-actions">
            <SourceTag
              v-if="srcOf(s.slotId, 'size')"
              :source="srcOf(s.slotId, 'size')!"
              :values="srcValuesOf(s.slotId, 'size')"
            />
            <button v-if="clearable && isOverridden(s.slotId, 'size')" type="button" class="ca-clear" @click="clearField(s.slotId, 'size')">不覆盖</button>
          </span>
        </div>
        <PageSegmented
          :model-value="strVal(s.slotId, 'size') || 'md'"
          :options="DRAWER_SIZE_OPTIONS"
          @update:model-value="(v) => config.setComponentKnob(s.slotId, 'size', String(v))"
        />
      </div>

      <div v-if="s.fields.includes('bodyScroll')" class="ca-item">
        <div class="ca-label-row">
          <span class="ca-label">内容区滚动</span>
          <span class="ca-actions">
            <SourceTag
              v-if="srcOf(s.slotId, 'bodyScroll')"
              :source="srcOf(s.slotId, 'bodyScroll')!"
              :values="srcValuesOf(s.slotId, 'bodyScroll')"
            />
            <button v-if="clearable && isOverridden(s.slotId, 'bodyScroll')" type="button" class="ca-clear" @click="clearField(s.slotId, 'bodyScroll')">不覆盖</button>
          </span>
        </div>
        <el-switch
          :model-value="boolVal(s.slotId, 'bodyScroll', true)"
          inline-prompt
          @update:model-value="(v: boolean) => config.setComponentKnob(s.slotId, 'bodyScroll', v)"
        />
      </div>

      <SettingsGroup
        v-if="s.fields.includes('hiddenColumns') && s.meta.columns?.length"
        title="列显隐"
        :level="showSlotTitle ? 3 : 2"
      >
        <template #actions>
          <span class="ca-actions">
            <SourceTag
              v-if="srcOf(s.slotId, 'hiddenColumns')"
              :source="srcOf(s.slotId, 'hiddenColumns')!"
              :values="srcValuesOf(s.slotId, 'hiddenColumns')"
            />
            <button v-if="clearable && isOverridden(s.slotId, 'hiddenColumns')" type="button" class="ca-clear" @click="clearField(s.slotId, 'hiddenColumns')">不覆盖</button>
          </span>
        </template>
        <PageToggleRow
          v-for="c in s.meta.columns"
          :key="c.key"
          size="sm"
          :label="`显示${c.label}`"
          :model-value="colVisible(s.slotId, c.key)"
          @update:model-value="(v) => setColVisible(s.slotId, c.key, v)"
        />
      </SettingsGroup>

      <div v-if="s.fields.includes('collapsibleSections')" class="ca-item">
        <div class="ca-label-row">
          <span class="ca-label">允许折叠分组</span>
          <span class="ca-actions">
            <SourceTag
              v-if="srcOf(s.slotId, 'collapsibleSections')"
              :source="srcOf(s.slotId, 'collapsibleSections')!"
              :values="srcValuesOf(s.slotId, 'collapsibleSections')"
            />
            <button v-if="clearable && isOverridden(s.slotId, 'collapsibleSections')" type="button" class="ca-clear" @click="clearField(s.slotId, 'collapsibleSections')">不覆盖</button>
          </span>
        </div>
        <el-switch
          :model-value="boolVal(s.slotId, 'collapsibleSections', true)"
          inline-prompt
          @update:model-value="(v: boolean) => config.setComponentKnob(s.slotId, 'collapsibleSections', v)"
        />
      </div>

      <div v-if="s.fields.includes('defaultCollapsed')" class="ca-item">
        <div class="ca-label-row">
          <span class="ca-label">默认折叠段</span>
          <span class="ca-actions">
            <SourceTag
              v-if="srcOf(s.slotId, 'defaultCollapsed')"
              :source="srcOf(s.slotId, 'defaultCollapsed')!"
              :values="srcValuesOf(s.slotId, 'defaultCollapsed')"
            />
            <button v-if="clearable && isOverridden(s.slotId, 'defaultCollapsed')" type="button" class="ca-clear" @click="clearField(s.slotId, 'defaultCollapsed')">不覆盖</button>
          </span>
        </div>
        <el-checkbox-group
          :model-value="listVal(s.slotId, 'defaultCollapsed')"
          @update:model-value="(v: string[]) => config.setComponentKnob(s.slotId, 'defaultCollapsed', v)"
        >
          <el-checkbox v-for="opt in visibleDrawerSectionOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </el-checkbox>
        </el-checkbox-group>
      </div>
    </SettingsGroup>
  </div>
  <el-empty v-else class="app-empty app-empty--compact" description="该页暂无可配置的组件" />
</template>

<style scoped>
.ca-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ca-item + .ca-item {
  margin-top: 4px;
}
.ca-label {
  font-size: 13px;
  color: var(--page-settings-text-subtle);
}
.ca-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.ca-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.ca-clear {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 12px;
  color: var(--page-settings-accent);
  cursor: pointer;
}
.ca-clear:hover {
  text-decoration: underline;
}
/* 页面布局「点击预览即配置」聚焦高亮 */
.ca-highlight {
  border-radius: 12px;
  box-shadow: 0 0 0 1px var(--page-settings-accent) inset;
}
</style>
