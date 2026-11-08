<script setup lang="ts">
import { formatNumber } from '@/utils/numberFormat'
/**
 * 页面布局工作台 · 结构示意预览（P5 / M8-C）。
 *
 * 不挂载真实业务组件，而是按 PageLayout schema 渲染**结构示意图**：操作区 + 主内容区（按设备档位
 * 计算列数与退化路径）+ overlay/嵌套对象清单。每个 slot 盒子展示组件种类、滚动归属、grow/重排能力、
 * 最低尺寸；点击 slot 查看其能力详情（聚焦）。契合需求 §5.7「优先占位、不依赖真实接口」。
 *
 * 设备档位与响应式策略命名见 plan.md §17.3。当前列数由 layout.responsive.breakpoints 推导
 * （多数页面 single-column，故各档恒为 1 列；dashboard 类重排页会在大档位显示多列）。
 */
import { computed, ref } from 'vue'
import PageSegmented from '@/components/PageSegmented.vue'
import { COMPONENT_CATALOG } from '../components'
import { DEVICE_TIERS, columnsAt, describeResponsive, type DeviceTier } from '../responsive'
import type { ResponsiveProfile } from '../pageRegistry'
import type { PageLayout, ScrollOwnership, SlotSpec } from '../schema'

const props = defineProps<{ layout: PageLayout; profile: ResponsiveProfile }>()
// 点击 slot 时通知父级（页面布局工作台据此把右侧配置面板聚焦到该组件，实现"点击预览即配置"，Q5）。
const emit = defineEmits<{ 'focus-slot': [slotId: string] }>()

const tier = ref<DeviceTier['key']>('laptop')
const currentTier = computed(() => DEVICE_TIERS.find((t) => t.key === tier.value)!)

/** 响应式摘要（P8）：策略命名/说明 + 三档列数 + 可重排/不可重排大表大图 slot 分类。 */
const summary = computed(() => describeResponsive(props.layout, props.profile))

const SCROLL_LABELS: Record<ScrollOwnership, string> = {
  none: '不滚动',
  'body-y': '纵向内滚',
  'body-xy': '双向内滚',
  region: '整区滚动',
}
function effScroll(s: SlotSpec): ScrollOwnership {
  return s.scroll ?? COMPONENT_CATALOG[s.component]?.defaultScroll ?? 'none'
}
function effMinW(s: SlotSpec): number {
  return s.minW ?? COMPONENT_CATALOG[s.component]?.minW ?? 0
}
function effMinH(s: SlotSpec): number {
  return s.minH ?? COMPONENT_CATALOG[s.component]?.minH ?? 0
}
function compLabel(s: SlotSpec): string {
  return COMPONENT_CATALOG[s.component]?.label ?? s.component
}

const actionSlots = computed(() => props.layout.slots.filter((s) => s.region === 'action' && !s.parentId).sort(byOrder))
const mainSlots = computed(() => props.layout.slots.filter((s) => s.region === 'main' && !s.parentId).sort(byOrder))
/** overlay 区 + 任意带 parentId 的嵌套 slot：不参与主流布局，单列清单展示。 */
const offFlowSlots = computed(() =>
  props.layout.slots.filter((s) => s.region === 'overlay' || s.parentId).sort(byOrder),
)
function byOrder(a: SlotSpec, b: SlotSpec) {
  return (a.order ?? 0) - (b.order ?? 0)
}

const currentColumns = computed(() => columnsAt(props.layout, currentTier.value.w))
/** 退化路径：三档各自列数，用于展示自适应退化。 */
const degradation = computed(() =>
  DEVICE_TIERS.map((t) => ({ key: t.key, label: t.short, w: t.w, columns: columnsAt(props.layout, t.w) })),
)
const isSinglePreviewShape = computed(() => {
  const cols = degradation.value.map((d) => d.columns)
  return cols.every((c) => c === cols[0])
})
const tierOptions = computed(() => degradation.value.map((item) => ({
  label: `${item.label} ${item.w}px · ${item.columns}列`,
  value: item.key,
})))
const uniformColumnCount = computed(() => degradation.value[0]?.columns ?? 1)

const focused = ref<string | null>(null)
function focus(id: string) {
  focused.value = id
  emit('focus-slot', id)
}
function parentLabel(s: SlotSpec): string | null {
  if (!s.parentId) return null
  const p = props.layout.slots.find((x) => x.id === s.parentId)
  return p ? (p.label || p.id) : s.parentId
}
</script>

<template>
  <div class="preview-wrap">
    <div class="preview-context">
      <div class="preview-context-main">
        <div class="preview-control-label">预览宽度</div>
        <PageSegmented
          v-if="!isSinglePreviewShape"
          v-model="tier"
          :options="tierOptions"
          tone="primary"
          aria-label="预览宽度"
        />
        <div v-else class="uniform-layout-note">
          三档宽度均为 <strong>{{ formatNumber(uniformColumnCount, 'count') }} 列</strong>，无需切换
        </div>
      </div>
      <div class="preview-context-note">
        仅查看响应式变化，不会修改页面配置
      </div>
    </div>

    <!-- 响应式摘要只保留策略与重排边界；档位列数已在上方宽度选择器中表达。 -->
    <div class="resp-summary">
      <div class="rs-strategy">
        <el-tag size="small" type="primary" effect="plain">响应策略 · {{ summary.profileLabel }}</el-tag>
        <span class="rs-desc">{{ summary.profileDesc }}</span>
      </div>
      <div class="rs-grid">
        <div class="rs-col">
          <div class="rs-h">可随宽度重排</div>
          <div class="rs-chips">
            <el-tag v-for="s in summary.reflowableSlots" :key="s.id" size="small" type="warning" effect="plain">{{ s.label }}</el-tag>
            <span v-if="!summary.reflowableSlots.length" class="muted">无</span>
          </div>
        </div>
        <div class="rs-col">
          <div class="rs-h">保持位置并内部滚动</div>
          <div class="rs-chips">
            <el-tag type="info" v-for="s in summary.lockedSlots" :key="s.id" size="small" effect="plain">
              {{ s.label }}<span v-if="s.growMain"> · 主区</span>
            </el-tag>
            <span v-if="!summary.lockedSlots.length" class="muted">—</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 结构示意框：操作区固定 + 主内容区按列数排布；纯示意、不跑真实组件。 -->
    <div class="device-frame">
      <div class="device-frame-head">
        <span>{{ currentTier.label }}</span>
        <span>当前 {{ currentColumns }} 列</span>
      </div>
        <div v-if="actionSlots.length" class="region-action">
          <div class="region-tag">操作区（固定）</div>
          <div class="action-row">
            <button
              v-for="s in actionSlots"
              :key="s.id"
              type="button"
              class="slot-box action"
              :class="{ active: focused === s.id }"
              @click="focus(s.id)"
            >
              <span class="slot-name">{{ s.label || s.id }}</span>
              <span class="slot-kind">{{ compLabel(s) }}</span>
            </button>
          </div>
        </div>

        <div class="region-main">
          <div class="region-tag">主内容区（吃剩余高度）</div>
          <div class="main-grid" :style="{ gridTemplateColumns: `repeat(${currentColumns}, minmax(0, 1fr))` }">
            <button
              v-for="s in mainSlots"
              :key="s.id"
              type="button"
              class="slot-box main"
              :class="{ active: focused === s.id, grow: s.growMain }"
              @click="focus(s.id)"
            >
              <div class="slot-head">
                <span class="slot-name">{{ s.label || s.id }}</span>
                <span class="slot-kind">{{ compLabel(s) }}</span>
              </div>
              <div class="slot-badges">
                <el-tag v-if="s.growMain" size="small" type="success" effect="plain">grow 主区</el-tag>
                <el-tag type="info" size="small" effect="plain">{{ SCROLL_LABELS[effScroll(s)] }}</el-tag>
                <el-tag v-if="s.reflowable ?? COMPONENT_CATALOG[s.component]?.reflowable" size="small" type="warning" effect="plain">可重排</el-tag>
              </div>
              <div class="slot-size">最低 {{ effMinW(s) }} x {{ effMinH(s) }}</div>
            </button>
          </div>
        </div>

      <div v-if="offFlowSlots.length" class="region-off-flow">
        <div class="region-tag">浮层与嵌套内容（不占页面主排版）</div>
        <div class="off-flow-grid">
            <button
              v-for="s in offFlowSlots"
              :key="s.id"
              type="button"
              class="slot-box off"
              :class="{ active: focused === s.id }"
              @click="focus(s.id)"
            >
              <span class="slot-name">{{ s.label || s.id }}</span>
              <span class="slot-kind app-inline-info">
                {{ compLabel(s) }}
                <span v-if="s.region === 'overlay'" class="off-tag">overlay</span>
                <span v-else-if="s.parentId" class="off-tag">嵌套于 {{ parentLabel(s) }}</span>
              </span>
            </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.preview-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}
.preview-context {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--app-space-4);
  flex-wrap: wrap;
}
.preview-context-main {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}
.preview-control-label {
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-regular);
}
.preview-context-note,
.uniform-layout-note {
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
}
.uniform-layout-note strong {
  color: var(--el-color-primary);
  font-weight: var(--app-font-weight-strong);
}
.resp-summary {
  border: 1px solid var(--app-border-subtle);
  border-radius: var(--layout-card-radius);
  background: var(--app-section-bg);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.rs-strategy {
  display: flex;
  align-items: baseline;
  gap: var(--app-space-2);
  flex-wrap: wrap;
}
.rs-desc {
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
}
.rs-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--app-space-3);
}
.rs-h {
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}
.rs-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-1);
}
@container app-viewport (max-width: 980px) {
  .rs-grid {
    grid-template-columns: 1fr;
  }
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.device-frame {
  border: 1px solid var(--app-border-subtle);
  border-radius: var(--layout-card-radius);
  background: var(--app-section-bg);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}
.device-frame-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-2);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.region-action,
.region-main,
.region-off-flow {
  border: 1px dashed var(--el-border-color);
  border-radius: var(--layout-card-radius);
  padding: 10px;
  background: var(--el-bg-color);
}
.region-off-flow {
  border-style: dotted;
}
.off-flow-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--app-space-2);
}
.region-tag {
  font-size: var(--app-font-size-micro);
  color: var(--el-text-color-secondary);
  margin-bottom: 8px;
}
.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-2);
}
.main-grid {
  display: grid;
  gap: var(--app-space-2);
}
.slot-box {
  text-align: left;
  border: 1px solid var(--app-border-subtle);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
  padding: 10px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-control-gap);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.slot-box:hover {
  border-color: var(--el-color-primary);
}
.slot-box.active {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px var(--el-color-primary) inset;
}
.slot-box.main.grow {
  min-height: 120px;
  background: color-mix(in srgb, var(--el-color-success) 7%, var(--el-bg-color));
}
.slot-box.action {
  flex-direction: row;
  align-items: baseline;
  gap: var(--app-space-2);
  padding: 6px 12px;
}
.slot-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--app-space-2);
}
.slot-name {
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-primary);
}
.slot-kind {
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
}
.slot-badges {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-1);
}
.slot-size {
  font-size: var(--app-font-size-micro);
  color: var(--el-text-color-secondary);
}
.slot-box.off {
  flex-direction: row;
  align-items: baseline;
  justify-content: space-between;
}
.off-tag {
  font-size: var(--app-font-size-micro);
  color: var(--el-color-warning);
}
@container app-viewport (max-width: 980px) {
  .off-flow-grid {
    grid-template-columns: 1fr;
  }
}
</style>
