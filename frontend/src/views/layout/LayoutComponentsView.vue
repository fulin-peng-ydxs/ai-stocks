<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppDataTable from '@/components/AppDataTable.vue'
/**
 * 系统组件工作区（P4 IA 重构起步，P6 补可视化预览）。
 *
 * 职责（plan.md §13.2 / requirement §5.7、§5.2）：把代码里的组件能力目录（COMPONENT_CATALOG）
 * 升级为可见的组件清单 + 可视化预览——按类别展示每个组件的尺寸下限、滚动归属、grow/reflow 能力、
 * 专属配置能力、可覆盖范围（来自 componentConfig 受控字段）、以及当前消费该组件的页面/slot；
 * 详情抽屉含 LayoutComponentPreview 的默认/loading/empty/error 四态预览。
 *
 * 边界（§6.3.1）：本页查看组件目录元信息并管理字段可覆盖范围，不引入 default<preset<page<user 之外的新运行时层。
 * 组件具体默认值分别在预设管理、页面布局、页面抽屉对应层编辑。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import LayoutComponentPreview from '@/layout/components/LayoutComponentPreview.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import HelpHint from '@/components/HelpHint.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import PageDrawer from '@/components/PageDrawer.vue'
import {
  COMPONENT_CATALOG,
  getPageLayout,
  getComponentFieldDefs,
  componentFieldApplicability,
  componentMetaForSlot,
  listComponentUsage,
  getPageEntry,
  type ComponentMeta,
  type ComponentState,
} from '@/layout'
import type { ComponentCategory, ComponentKind, ScrollOwnership } from '@/layout'
import {
  listFieldPolicies,
  saveFieldPolicy,
  type ComponentConfigLayer,
  type FieldPolicyRecord,
} from '@/api/layout'
import { getErrorMessage } from '@/utils/error'
import type { AppRowAction } from '@/components/rowActions'

const componentsLayout = getPageLayout('layout-components')

const CATEGORY_LABELS: Record<ComponentCategory, string> = {
  structure: '页面结构',
  query: '查询操作',
  display: '数据展示',
  'table-addon': '表格附属',
  form: '表单输入',
  feedback: '反馈状态',
  analytics: '数据摘要 / 图表',
  overlay: '详情 / 浮层',
  complex: '复杂布局',
  navigation: '导航辅助',
}
const CATEGORY_ORDER: ComponentCategory[] = [
  'structure', 'query', 'display', 'table-addon', 'form',
  'feedback', 'analytics', 'overlay', 'complex', 'navigation',
]
const SCROLL_LABELS: Record<ScrollOwnership, string> = {
  none: '不滚动',
  'body-y': '纵向内滚',
  'body-xy': '双向内滚',
  region: '整区滚动',
}
function scrollLabel(s: ScrollOwnership): string {
  return SCROLL_LABELS[s] ?? s
}

interface ConfigurableField {
  key: string
  label: string
  /** 可覆盖范围摘要文案（当前生效开放集）。 */
  layers: string
  /** 代码声明的最大开放集（收放上界，复选框超出此集禁用）。 */
  maxLayers: ComponentConfigLayer[]
  /** 当前生效开放集（复选框勾选态）。 */
  allowedLayers: ComponentConfigLayer[]
  /** 是否被管理员覆盖（非代码最大集）。 */
  overridden: boolean
}

interface ComponentRow extends ComponentMeta {
  /** 可被 Web 配置的字段及其可覆盖范围（空表示尚未开放受控配置）。 */
  configurableFields: ConfigurableField[]
  /** 消费该组件的页面（按页面去重，附 slot 数）。 */
  usagePages: string[]
  usageCoverage: UsageCoverageRow[]
}

interface UsageCoverageRow {
  key: string
  page: string
  slot: string
  field: string
  status: 'inherited' | 'blocked' | 'not-applicable'
  statusLabel: string
  reason: string
}

const LAYER_LABELS: Record<string, string> = { preset: '预设', page: '页面', user: '个人' }
const ALL_LAYERS: ComponentConfigLayer[] = ['preset', 'page', 'user']

// 可覆盖范围（后端 layout_field_policy）：键 `${kind}.${field}`。挂载后拉取，编辑即时刷新。
const policyMap = ref<Map<string, FieldPolicyRecord>>(new Map())
const policyError = ref('')
const policyLoading = ref(true)

function buildRow(meta: ComponentMeta): ComponentRow {
  const fieldDefs = getComponentFieldDefs(meta.kind)
  const configurableFields: ConfigurableField[] = fieldDefs.map((def) => {
    const policy = policyMap.value.get(`${meta.kind}.${def.key}`)
    // 策略未加载时回落代码定义（def.layers 即代码最大集），避免首屏空白。
    const maxLayers = (policy?.maxLayers ?? def.layers) as ComponentConfigLayer[]
    const allowedLayers = (policy?.allowedLayers ?? def.layers) as ComponentConfigLayer[]
    return {
      key: def.key,
      label: def.label,
      layers: allowedLayers.map((l) => LAYER_LABELS[l] ?? l).join('/') || '（未开放）',
      maxLayers,
      allowedLayers,
      overridden: policy?.overridden ?? false,
    }
  })
  const usage = listComponentUsage(meta.kind)
  const byPage = new Map<string, number>()
  for (const u of usage) byPage.set(u.label, (byPage.get(u.label) ?? 0) + 1)
  const usagePages = [...byPage.entries()].map(([label, n]) => (n > 1 ? `${label}×${n}` : label))
  const usageCoverage: UsageCoverageRow[] = []
  for (const item of usage) {
    const entry = getPageEntry(item.pageKey)
    const slot = entry?.layout.slots.find((candidate) => candidate.id === item.slotId)
    if (!entry || !slot) continue
    const slotMeta = componentMetaForSlot(entry, slot)
    for (const def of fieldDefs.filter((field) => field.layers.includes('user'))) {
      const applicability = componentFieldApplicability(def, slotMeta)
      const allowed = policyMap.value.get(`${meta.kind}.${def.key}`)?.allowedLayers ?? def.layers
      const status: UsageCoverageRow['status'] = !applicability.applicable
        ? 'not-applicable'
        : allowed.includes('user')
          ? 'inherited'
          : 'blocked'
      usageCoverage.push({
        key: `${item.pageKey}.${item.slotId}.${def.key}`,
        page: entry.label,
        slot: `${slot.label || slot.id}（${slot.id}）`,
        field: def.label,
        status,
        statusLabel: status === 'inherited' ? '自动继承' : status === 'blocked' ? '策略关闭' : '不适用',
        reason: status === 'inherited'
          ? '组件种类个人字段自动进入该页面抽屉'
          : status === 'blocked'
            ? '当前字段开放策略不包含个人层'
            : applicability.reason,
      })
    }
  }
  return { ...meta, configurableFields, usagePages, usageCoverage }
}

async function loadPolicies(): Promise<void> {
  policyLoading.value = true
  policyError.value = ''
  try {
    const { policies } = await listFieldPolicies()
    const map = new Map<string, FieldPolicyRecord>()
    for (const p of policies) map.set(`${p.componentKind}.${p.field}`, p)
    policyMap.value = map
  } catch (error) {
    policyError.value = getErrorMessage(error, '组件字段策略加载失败')
    /* 离线 / 接口失败：保持代码默认展示，不阻塞页面 */
  } finally {
    policyLoading.value = false
  }
}
onMounted(loadPolicies)

const groups = computed(() => {
  const all = (Object.keys(COMPONENT_CATALOG) as ComponentKind[]).map((k) => buildRow(COMPONENT_CATALOG[k]))
  return CATEGORY_ORDER.map((cat) => ({
    category: cat,
    label: CATEGORY_LABELS[cat],
    rows: all.filter((r) => r.category === cat),
  })).filter((g) => g.rows.length)
})

const totalCount = computed(() => Object.keys(COMPONENT_CATALOG).length)
const consumedCount = computed(() =>
  (Object.keys(COMPONENT_CATALOG) as ComponentKind[]).filter((k) => listComponentUsage(k).length).length,
)
const configurableCount = computed(() =>
  (Object.keys(COMPONENT_CATALOG) as ComponentKind[]).filter((k) => getComponentFieldDefs(k).length).length,
)

const activeNames = ref(CATEGORY_ORDER.map((c) => c as string))

// 组件详情抽屉（预览 + 能力 + 可覆盖范围编辑 + 消费页面）。
// selected 按 kind 派生，使可覆盖范围编辑后实时回显（policyMap 变 → buildRow 重算）。
const detailVisible = ref(false)
const selectedKind = ref<ComponentKind | null>(null)
const selected = computed<ComponentRow | null>(() =>
  selectedKind.value ? buildRow(COMPONENT_CATALOG[selectedKind.value]) : null,
)
const previewState = ref<ComponentState>('ready')
const PREVIEW_STATES: { value: ComponentState; label: string }[] = [
  { value: 'ready', label: '默认' },
  { value: 'loading', label: '加载中' },
  { value: 'empty', label: '空态' },
  { value: 'error', label: '错误' },
]
/** 组件共同特性（所有组件统一具备，requirement §5.2）；与专属特性分列，避免 AI 随意扩字段。 */
const COMMON_FEATURES = [
  'id / kind / label 标识与显示名',
  'region 区域归属（action / main / overlay）',
  'order 排序 · visible 显隐 · permission 权限',
  'styleTokens 样式 token',
  'minW·minH / idealW·idealH / maxW·maxH 尺寸',
  'scroll 滚动归属',
  'growMain 主区成长 · reflowable 可重排',
  'states 状态占位（loading/empty/error 同尺寸）',
  'dataBinding 数据绑定 · actions 动作',
  'editable 可配置白名单',
]
function openDetail(row: ComponentRow) {
  selectedKind.value = row.kind
  previewState.value = 'ready'
  detailVisible.value = true
}

function componentRowActions(row: ComponentRow): AppRowAction[] {
  return [
    { key: 'preview', label: '预览', onClick: () => openDetail(row) },
  ]
}

function fieldPolicyRowActions(row: ConfigurableField): AppRowAction[] {
  return [
    {
      key: 'reset',
      label: '恢复默认',
      permission: 'layout:field-policy',
      onClick: () => resetField(row.key),
    },
  ]
}

function fieldMaxLayers(row: ConfigurableField): ComponentConfigLayer[] {
  if (Array.isArray(row.maxLayers)) return row.maxLayers
  return getComponentFieldDefs(selectedKind.value ?? 'section')
    .find((def) => def.key === row.key)?.layers ?? []
}

function fieldAllowedLayers(row: ConfigurableField): ComponentConfigLayer[] {
  return Array.isArray(row.allowedLayers) ? row.allowedLayers : fieldMaxLayers(row)
}

/** 更新某字段可覆盖范围并即时刷新 policyMap（写后端 layout_field_policy）。 */
async function persistPolicy(field: string, layers: ComponentConfigLayer[]): Promise<void> {
  const kind = selectedKind.value
  if (!kind) return
  try {
    const rec = await saveFieldPolicy({ componentKind: kind, field, allowedLayers: layers })
    const next = new Map(policyMap.value)
    next.set(`${kind}.${field}`, rec)
    policyMap.value = next
    ElMessage.success('可覆盖范围已更新')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
    void loadPolicies() // 失败回拉，撤销 UI 乐观态
  }
}

/** 复选框改动：至少保留一层；清空则提示并撤销（后端也会拒绝空集）。 */
function onLayersChange(field: string, layers: ComponentConfigLayer[]): void {
  const ordered = ALL_LAYERS.filter((l) => layers.includes(l))
  if (!ordered.length) {
    ElMessage.warning('至少保留一个开放层级')
    void loadPolicies()
    return
  }
  void persistPolicy(field, ordered)
}

/** 恢复某字段为代码最大集（后端按空数组重置）。 */
function resetField(field: string): void {
  void persistPolicy(field, [])
}
function sizeText(meta: ComponentRow, key: 'W' | 'H'): string {
  const min = meta[`min${key}`]
  const ideal = meta[`ideal${key}`]
  const max = meta[`max${key}`]
  return [min != null ? `最低 ${min}` : null, ideal != null ? `理想 ${ideal}` : null, max != null ? `最大 ${max}` : null]
    .filter(Boolean)
    .join(' · ') || '—'
}

</script>

<template>
  <LayoutHost :layout="componentsLayout">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <div>
            <h2 class="app-page-title page-title-row">
              系统组件
              <HelpTip title="系统组件说明" :width="420">
                <HelpTipItem question="当前目录包含哪些组件">
                  <ul>
                    <li>共 {{ totalCount }} 种组件，{{ consumedCount }} 种已被页面消费，{{ configurableCount }} 种已开放 Web 配置。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="如何查看和配置">
                  <ul>
                    <li>使用“预览”查看四态规范样板与字段可覆盖范围；可覆盖范围在本页编辑，组件默认值在“预设管理”中维护。</li>
                  </ul>
                </HelpTipItem>
              </HelpTip>
            </h2>
            <p class="page-subtitle">查看系统组件能力、页面使用情况与可配置字段范围。</p>
          </div>
        </div>
      </div>
    </template>

    <template #main>
      <section
        v-loading="policyLoading"
        element-loading-text="正在加载组件字段策略…"
        class="plain-panel"
        :aria-busy="policyLoading"
        data-testid="component-catalog"
      >
        <AppStateBlock
          v-if="policyError"
          state="error"
          size="compact"
          title="组件字段策略加载失败"
          :description="policyError"
          retry
          @retry="loadPolicies"
        />
        <el-collapse v-else v-model="activeNames">
          <el-collapse-item v-for="group in groups" :key="group.category" :name="group.category">
            <template #title>
              <span class="cat-title">{{ group.label }}</span>
              <span class="cat-count">{{ group.rows.length }}</span>
            </template>
            <AppDataTable :data="group.rows" row-key="kind" size="small" embedded>
              <AppTableColumn label="组件">
                <template #default="{ row }">
                  <div class="comp-name">{{ row.label }}</div>
                  <div class="muted">{{ row.kind }}</div>
                </template>
              </AppTableColumn>
              <AppTableColumn label="说明">
                <template #default="{ row }">{{ row.description }}</template>
              </AppTableColumn>
              <AppTableColumn label="最低尺寸">
                <template #default="{ row }">{{ row.minW }}×{{ row.minH }}</template>
              </AppTableColumn>
              <AppTableColumn label="滚动">
                <template #default="{ row }">{{ scrollLabel(row.defaultScroll) }}</template>
              </AppTableColumn>
              <AppTableColumn label="能力">
                <template #default="{ row }">
                  <el-tag v-if="row.canGrowMain" size="small" type="success" effect="plain">主区可成长</el-tag>
                  <el-tag v-if="row.reflowable" size="small" type="warning" effect="plain">可重排</el-tag>
                  <span v-if="!row.canGrowMain && !row.reflowable" class="muted">—</span>
                </template>
              </AppTableColumn>
              <AppTableColumn label="专属配置能力">
                <template #default="{ row }">
                  <span class="caps">{{ row.configCapabilities.join('、') || '—' }}</span>
                </template>
              </AppTableColumn>
              <AppTableColumn label="已开放 Web 配置（可覆盖范围）">
                <template #default="{ row }">
                  <div v-if="row.configurableFields.length" class="field-chips">
                    <el-tag v-for="f in row.configurableFields" :key="f.key" size="small" effect="plain">
                      {{ f.label }}（{{ f.layers }}）
                    </el-tag>
                  </div>
                  <span v-else class="muted">未开放</span>
                </template>
              </AppTableColumn>
              <AppTableColumn label="消费页面">
                <template #default="{ row }">
                  <span v-if="row.usagePages.length">{{ row.usagePages.join('、') }}</span>
                  <span v-else class="muted">暂无页面消费</span>
                </template>
              </AppTableColumn>
              <AppTableColumn label="操作" role="action-compact" fixed="right">
                <template #default="{ row }">
                  <AppRowActions
                    :actions="componentRowActions(row)"
                    :inline-limit="1"
                    :test-id="`component-catalog-${row.kind}`"
                  />
                </template>
              </AppTableColumn>
            </AppDataTable>
          </el-collapse-item>
        </el-collapse>
      </section>
    </template>

    <template #overlays>
      <PageDrawer
        :model-value="detailVisible"
        @update:model-value="(value: boolean) => { detailVisible = value }"
        :title="selected ? `${selected.label}（${selected.kind}）` : '组件详情'"
        size="xl"
        data-testid="component-preview-drawer"
      >
        <div v-if="selected" class="detail-body">
          <div class="detail-block">
            <div class="db-head">
              <span class="db-title">四态规范预览</span>
              <HelpHint text="给开发与验收人员对照该组件种类的 ready / loading / empty / error 规范；不是业务页面截图，也不代表消费页面已经接入。非 ready 态与真实页面共用 AppStateBlock。" />
              <el-radio-group v-model="previewState" size="small" style="margin-left:auto">
                <el-radio-button
                  v-for="s in PREVIEW_STATES"
                  :key="s.value"
                  :value="s.value"
                  :data-testid="`component-state-${s.value}`"
                >{{ s.label }}</el-radio-button>
              </el-radio-group>
            </div>
            <LayoutComponentPreview :kind="selected.kind" :state="previewState" />
            <div class="preview-purpose app-caption-text">
              用途：统一状态语义、文案和稳定占位；业务页面仍需接入真实数据并单独通过四态测试。
            </div>
          </div>

          <div class="detail-block">
            <div class="db-title">能力说明</div>
            <el-descriptions :column="1" size="small" border>
              <el-descriptions-item label="说明">
                <span class="app-body-text">{{ selected.description }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="类别">{{ CATEGORY_LABELS[selected.category] }}</el-descriptions-item>
              <el-descriptions-item label="宽度">{{ sizeText(selected, 'W') }}</el-descriptions-item>
              <el-descriptions-item label="高度">{{ sizeText(selected, 'H') }}</el-descriptions-item>
              <el-descriptions-item label="滚动归属">{{ scrollLabel(selected.defaultScroll) }}</el-descriptions-item>
              <el-descriptions-item label="能力">
                <el-tag v-if="selected.canGrowMain" size="small" type="success" effect="plain">主区可成长</el-tag>
                <el-tag v-if="selected.reflowable" size="small" type="warning" effect="plain">可重排</el-tag>
                <span v-if="!selected.canGrowMain && !selected.reflowable" class="muted">不成长 / 不重排</span>
              </el-descriptions-item>
              <el-descriptions-item label="自适应">
                <span v-if="selected.category === 'overlay'">overlay：固定尺寸档位（size / maxHeight），不参与页面多列重排</span>
                <span v-else-if="selected.reflowable">满足最低宽度时可参与多列重排</span>
                <span v-else>不重排——靠内部滚动消化高度，不靠拆列解决</span>
              </el-descriptions-item>
            </el-descriptions>
          </div>

          <div class="detail-block">
            <div class="db-title">专属特性</div>
            <div class="chip-row">
              <el-tag v-for="c in selected.configCapabilities" :key="c" size="small" effect="plain">{{ c }}</el-tag>
              <span v-if="!selected.configCapabilities.length" class="muted">—</span>
            </div>
          </div>

          <div class="detail-block">
            <div class="db-head">
              <span class="db-title">可覆盖范围（在线编辑）</span>
              <HelpHint text="勾选某字段允许在哪些层被覆盖（预设 / 页面 / 个人）。灰色项=代码未声明、不可开放（安全红线）。组件默认值请到「预设管理」按预设设置。" />
            </div>
            <AppDataTable v-if="selected.configurableFields.length" :data="selected.configurableFields" size="small" embedded>
              <AppTableColumn label="字段">
                <template #default="{ row }">
                  <div class="comp-name">{{ row.label }}</div>
                  <div class="muted">{{ row.key }}</div>
                </template>
              </AppTableColumn>
              <AppTableColumn label="允许覆盖范围">
                <template #default="{ row }">
                  <el-checkbox-group
                    v-permission="'layout:field-policy'"
                    :model-value="fieldAllowedLayers(row)"
                    @change="(v: ComponentConfigLayer[]) => onLayersChange(row.key, v)"
                  >
                    <el-checkbox
                      v-for="l in ALL_LAYERS"
                      :key="l"
                      :value="l"
                      :disabled="!fieldMaxLayers(row).includes(l)"
                    >{{ LAYER_LABELS[l] }}</el-checkbox>
                  </el-checkbox-group>
                </template>
              </AppTableColumn>
              <AppTableColumn label="" align="right">
                <template #default="{ row }">
                  <AppRowActions
                    v-if="row.overridden"
                    :actions="fieldPolicyRowActions(row)"
                    :inline-limit="1"
                  />
                  <span v-else class="muted">默认</span>
                </template>
              </AppTableColumn>
            </AppDataTable>
            <div v-else class="muted">该组件未登记受控字段——仅代码默认（default），无可在线收放的覆盖范围。</div>
          </div>

          <div class="detail-block">
            <div class="db-title">共同特性</div>
            <ul class="feature-list">
              <li v-for="f in COMMON_FEATURES" :key="f">{{ f }}</li>
            </ul>
          </div>

          <div class="detail-block">
            <div class="db-title">消费页面</div>
            <div class="chip-row">
              <el-tag v-for="p in selected.usagePages" :key="p" size="small" type="info" effect="plain">{{ p }}</el-tag>
              <span v-if="!selected.usagePages.length" class="muted">暂无页面消费</span>
            </div>
          </div>

          <div class="detail-block">
            <div class="db-head">
              <span class="db-title">个人层自动继承覆盖</span>
              <HelpHint text="组件种类中开放个人层的字段会自动进入所有适用 slot 的页面设置抽屉；不适用必须由实例候选缺失或明确例外解释，不能靠页面漏登记。" />
            </div>
            <AppDataTable
              v-if="selected.usageCoverage.length"
              :data="selected.usageCoverage"
              size="small"
              embedded
              data-testid="component-user-field-coverage"
            >
              <AppTableColumn prop="page" label="页面" />
              <AppTableColumn prop="slot" label="组件实例" />
              <AppTableColumn prop="field" label="个人字段" />
              <AppTableColumn label="状态">
                <template #default="{ row }">
                  <el-tag
                    size="small"
                    effect="plain"
                    :type="row.status === 'inherited' ? 'success' : row.status === 'blocked' ? 'info' : 'warning'"
                  >{{ row.statusLabel }}</el-tag>
                </template>
              </AppTableColumn>
              <AppTableColumn prop="reason" label="依据" />
            </AppDataTable>
            <div v-else class="muted">该组件没有个人层字段，或尚无页面消费。</div>
          </div>

          <el-alert
            type="info"
            :closable="false"
            title="边界：系统组件库只管理组件目录元信息与受控默认策略，不新增运行时优先级层（运行时仍为 default < preset < page < user）。"
          />
        </div>
      </PageDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.muted {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.page-title-row {
  display: flex;
  align-items: center;
  gap: var(--app-space-1);
}
.plain-panel {
  min-width: 0;
  border: 1px solid var(--el-border-color);
  background: var(--el-bg-color);
  border-radius: 6px;
  padding: 8px 14px 14px;
}
.cat-title {
  font-size: var(--app-font-size-body);
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-primary);
}
.cat-count {
  margin-left: 8px;
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
}
.comp-name {
  font-weight: var(--app-font-weight-section);
}
.caps {
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-regular);
}
.field-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-1);
}
.detail-body {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
}
.detail-block {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.db-head {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: var(--app-space-2);
}
.db-title {
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-primary);
}
.db-hint {
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
}
.preview-purpose {
  color: var(--el-text-color-secondary);
  line-height: var(--app-line-height-body);
}
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-control-gap);
}
.feature-list {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-regular);
}
</style>
