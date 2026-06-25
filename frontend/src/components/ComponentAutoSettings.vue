<script setup lang="ts">
/**
 * 「组件设置」段自动渲染——由 pageRegistry 的 consumedComponentFields + componentMeta 驱动，
 * 各页不再手写列开关/排序/分页控件。每个被消费的 slot 渲染一个 SettingsGroup（level 2），
 * 内含：默认排序（可排序字段下拉 + 方向）、每页条数、列显隐（独立 level 3 子组，每列一个开关）。
 * 写值统一经组件配置层（setComponentKnob → 用户层），与配置中心/后端校验同源。
 */
import { computed } from 'vue'
import SettingsGroup from './SettingsGroup.vue'
import PageSegmented from './PageSegmented.vue'
import PageToggleRow from './PageToggleRow.vue'
import SourceTag from './SourceTag.vue'
import { getPageEntry, type SlotConfigMeta } from '@/layout/pageRegistry'
import type { ComponentConfigSource } from '@/layout/componentConfig'

interface ComponentConfigAccess {
  componentValueOf: (slotId: string, field: string) => unknown
  setComponentKnob: (slotId: string, field: string, value: unknown) => void
  /** 可选：读字段生效来源层，用于展示来源徽标（default/preset/page/user）。 */
  componentSourceOf?: (slotId: string, field: string) => ComponentConfigSource
  /** 可选：读字段逐层取值，用于来源 hover 展示。 */
  componentLayerValuesOf?: (slotId: string, field: string) => Partial<Record<ComponentConfigSource, unknown>>
}

function srcOf(slotId: string, field: string): ComponentConfigSource | null {
  return props.config.componentSourceOf ? props.config.componentSourceOf(slotId, field) : null
}
function srcValuesOf(slotId: string, field: string) {
  return props.config.componentLayerValuesOf?.(slotId, field)
}

const props = defineProps<{ pageKey: string; config: ComponentConfigAccess }>()

interface AutoSlot {
  slotId: string
  label: string
  fields: string[]
  meta: SlotConfigMeta
}

const autoSlots = computed<AutoSlot[]>(() => {
  const entry = getPageEntry(props.pageKey)
  if (!entry?.consumedComponentFields) return []
  const byId = new Map(entry.layout.slots.map((s) => [s.id, s]))
  const meta = entry.componentMeta ?? {}
  return Object.entries(entry.consumedComponentFields).map(([slotId, fields]) => ({
    slotId,
    label: byId.get(slotId)?.label || slotId,
    // 页面设置抽屉是用户层入口，只渲染允许 user 层修改的字段；collapsibleSections 属预设/页面策略。
    fields: fields.filter((field) => field !== 'collapsibleSections'),
    meta: meta[slotId] ?? {},
  })).filter((slot) => slot.fields.length)
})

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
  <template v-if="autoSlots.length">
    <SettingsGroup v-for="s in autoSlots" :key="s.slotId" :title="s.label" :level="2">
      <template v-if="s.fields.includes('defaultSort') && s.meta.sortFields?.length">
        <!-- field:order 模式：字段 + 方向 -->
        <div v-if="s.meta.sortHasDirection !== false" class="ca-item">
          <div class="ca-label-row">
            <span class="ca-label">默认排序字段</span>
            <SourceTag
              v-if="srcOf(s.slotId, 'defaultSort')"
              :source="srcOf(s.slotId, 'defaultSort')!"
              :values="srcValuesOf(s.slotId, 'defaultSort')"
            />
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
            <SourceTag
              v-if="srcOf(s.slotId, 'defaultSort')"
              :source="srcOf(s.slotId, 'defaultSort')!"
              :values="srcValuesOf(s.slotId, 'defaultSort')"
            />
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
          <SourceTag
            v-if="srcOf(s.slotId, 'pageSize')"
            :source="srcOf(s.slotId, 'pageSize')!"
            :values="srcValuesOf(s.slotId, 'pageSize')"
          />
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
          <SourceTag
            v-if="srcOf(s.slotId, 'defaultActive')"
            :source="srcOf(s.slotId, 'defaultActive')!"
            :values="srcValuesOf(s.slotId, 'defaultActive')"
          />
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
          <SourceTag
            v-if="srcOf(s.slotId, 'size')"
            :source="srcOf(s.slotId, 'size')!"
            :values="srcValuesOf(s.slotId, 'size')"
          />
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
          <SourceTag
            v-if="srcOf(s.slotId, 'bodyScroll')"
            :source="srcOf(s.slotId, 'bodyScroll')!"
            :values="srcValuesOf(s.slotId, 'bodyScroll')"
          />
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
        :level="3"
      >
        <div class="ca-label-row">
          <span class="ca-label">当前隐藏列</span>
          <SourceTag
            v-if="srcOf(s.slotId, 'hiddenColumns')"
            :source="srcOf(s.slotId, 'hiddenColumns')!"
            :values="srcValuesOf(s.slotId, 'hiddenColumns')"
          />
        </div>
        <PageToggleRow
          v-for="c in s.meta.columns"
          :key="c.key"
          :label="`显示${c.label}`"
          :model-value="colVisible(s.slotId, c.key)"
          @update:model-value="(v) => setColVisible(s.slotId, c.key, v)"
        />
      </SettingsGroup>

      <div v-if="s.fields.includes('collapsibleSections')" class="ca-item">
        <div class="ca-label-row">
          <span class="ca-label">允许折叠分组</span>
          <SourceTag
            v-if="srcOf(s.slotId, 'collapsibleSections')"
            :source="srcOf(s.slotId, 'collapsibleSections')!"
            :values="srcValuesOf(s.slotId, 'collapsibleSections')"
          />
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
          <SourceTag
            v-if="srcOf(s.slotId, 'defaultCollapsed')"
            :source="srcOf(s.slotId, 'defaultCollapsed')!"
            :values="srcValuesOf(s.slotId, 'defaultCollapsed')"
          />
        </div>
        <el-checkbox-group
          :model-value="listVal(s.slotId, 'defaultCollapsed')"
          @update:model-value="(v: string[]) => config.setComponentKnob(s.slotId, 'defaultCollapsed', v)"
        >
          <el-checkbox v-for="opt in DRAWER_SECTION_OPTIONS" :key="opt.value" :label="opt.value">
            {{ opt.label }}
          </el-checkbox>
        </el-checkbox-group>
      </div>
    </SettingsGroup>
  </template>
  <el-empty v-else description="该页暂无可配置的组件" :image-size="48" />
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
</style>
