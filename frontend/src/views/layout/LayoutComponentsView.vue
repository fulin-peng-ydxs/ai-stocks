<script setup lang="ts">
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
import AppStateBlock from '@/components/AppStateBlock.vue'
import HelpHint from '@/components/HelpHint.vue'
import PageDrawer from '@/components/PageDrawer.vue'
import {
  COMPONENT_CATALOG,
  getPageLayout,
  getComponentFieldDefs,
  listComponentUsage,
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
}

const LAYER_LABELS: Record<string, string> = { preset: '预设', page: '页面', user: '个人' }
const ALL_LAYERS: ComponentConfigLayer[] = ['preset', 'page', 'user']

// 可覆盖范围（后端 layout_field_policy）：键 `${kind}.${field}`。挂载后拉取，编辑即时刷新。
const policyMap = ref<Map<string, FieldPolicyRecord>>(new Map())
const policyError = ref('')

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
  return { ...meta, configurableFields, usagePages }
}

async function loadPolicies(): Promise<void> {
  policyError.value = ''
  try {
    const { policies } = await listFieldPolicies()
    const map = new Map<string, FieldPolicyRecord>()
    for (const p of policies) map.set(`${p.componentKind}.${p.field}`, p)
    policyMap.value = map
  } catch (error) {
    policyError.value = getErrorMessage(error, '组件字段策略加载失败')
    /* 离线 / 接口失败：保持代码默认展示，不阻塞页面 */
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
      <div class="layout-toolbar">
        <div>
          <div class="page-title">系统组件</div>
          <div class="page-subtitle">
            组件能力目录：共 {{ totalCount }} 种 · {{ consumedCount }} 种被页面消费 · {{ configurableCount }} 种已开放 Web 配置；点「预览」可在线编辑字段可覆盖范围
          </div>
        </div>
        <div class="toolbar-actions">
          <el-tag type="success" effect="plain">可覆盖范围可编辑 · 组件默认请到「预设管理」</el-tag>
        </div>
      </div>
    </template>

    <template #main>
      <section class="plain-panel">
        <AppStateBlock
          v-if="policyError"
          state="error"
          size="compact"
          title="组件字段策略加载失败"
          :description="policyError"
          retry
          @retry="loadPolicies"
        />
        <el-collapse v-model="activeNames">
          <el-collapse-item v-for="group in groups" :key="group.category" :name="group.category">
            <template #title>
              <span class="cat-title">{{ group.label }}</span>
              <span class="cat-count">{{ group.rows.length }}</span>
            </template>
            <el-table :data="group.rows" row-key="kind" size="small">
              <el-table-column label="组件" min-width="150">
                <template #default="{ row }">
                  <div class="comp-name">{{ row.label }}</div>
                  <div class="muted">{{ row.kind }}</div>
                </template>
              </el-table-column>
              <el-table-column label="说明" min-width="180" show-overflow-tooltip>
                <template #default="{ row }">{{ row.description }}</template>
              </el-table-column>
              <el-table-column label="最低尺寸" width="100">
                <template #default="{ row }">{{ row.minW }}×{{ row.minH }}</template>
              </el-table-column>
              <el-table-column label="滚动" width="90">
                <template #default="{ row }">{{ scrollLabel(row.defaultScroll) }}</template>
              </el-table-column>
              <el-table-column label="能力" width="120">
                <template #default="{ row }">
                  <el-tag v-if="row.canGrowMain" size="small" type="success" effect="plain">主区可成长</el-tag>
                  <el-tag v-if="row.reflowable" size="small" type="warning" effect="plain">可重排</el-tag>
                  <span v-if="!row.canGrowMain && !row.reflowable" class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column label="专属配置能力" min-width="180">
                <template #default="{ row }">
                  <span class="caps">{{ row.configCapabilities.join('、') || '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="已开放 Web 配置（可覆盖范围）" min-width="190">
                <template #default="{ row }">
                  <div v-if="row.configurableFields.length" class="field-chips">
                    <el-tag v-for="f in row.configurableFields" :key="f.key" size="small" effect="plain">
                      {{ f.label }}（{{ f.layers }}）
                    </el-tag>
                  </div>
                  <span v-else class="muted">未开放</span>
                </template>
              </el-table-column>
              <el-table-column label="消费页面" min-width="150">
                <template #default="{ row }">
                  <span v-if="row.usagePages.length">{{ row.usagePages.join('、') }}</span>
                  <span v-else class="muted">暂无页面消费</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="92" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" @click="openDetail(row)">预览</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-collapse-item>
        </el-collapse>
      </section>
    </template>

    <template #overlays>
      <PageDrawer v-model="detailVisible" :title="selected ? `${selected.label}（${selected.kind}）` : '组件详情'" size="560px">
        <div v-if="selected" class="detail-body">
          <div class="detail-block">
            <div class="db-head">
              <span class="db-title">可视化预览</span>
              <HelpHint text="代表性占位示意（不挂载真实组件）；四态切换不改变外层尺寸。" />
              <el-radio-group v-model="previewState" size="small" style="margin-left:auto">
                <el-radio-button v-for="s in PREVIEW_STATES" :key="s.value" :value="s.value">{{ s.label }}</el-radio-button>
              </el-radio-group>
            </div>
            <LayoutComponentPreview :kind="selected.kind" :state="previewState" />
          </div>

          <div class="detail-block">
            <div class="db-title">能力说明</div>
            <el-descriptions :column="1" size="small" border>
              <el-descriptions-item label="说明">{{ selected.description }}</el-descriptions-item>
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
            <el-table v-if="selected.configurableFields.length" :data="selected.configurableFields" size="small">
              <el-table-column label="字段" min-width="130">
                <template #default="{ row }">
                  <div class="comp-name">{{ row.label }}</div>
                  <div class="muted">{{ row.key }}</div>
                </template>
              </el-table-column>
              <el-table-column label="允许覆盖范围" min-width="200">
                <template #default="{ row }">
                  <el-checkbox-group
                    v-permission="'layout:field-policy'"
                    :model-value="row.allowedLayers"
                    @change="(v: ComponentConfigLayer[]) => onLayersChange(row.key, v)"
                  >
                    <el-checkbox
                      v-for="l in ALL_LAYERS"
                      :key="l"
                      :value="l"
                      :disabled="!row.maxLayers.includes(l)"
                    >{{ LAYER_LABELS[l] }}</el-checkbox>
                  </el-checkbox-group>
                </template>
              </el-table-column>
              <el-table-column label="" width="96" align="right">
                <template #default="{ row }">
                  <el-button v-permission="'layout:field-policy'" v-if="row.overridden" size="small" text type="primary" @click="resetField(row.key)">恢复默认</el-button>
                  <span v-else class="muted">默认</span>
                </template>
              </el-table-column>
            </el-table>
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
.layout-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--el-border-color);
  background: var(--el-bg-color);
  border-radius: 6px;
}
.page-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.page-subtitle,
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.plain-panel {
  min-width: 0;
  border: 1px solid var(--el-border-color);
  background: var(--el-bg-color);
  border-radius: 6px;
  padding: 8px 14px 14px;
}
.cat-title {
  font-size: 14px;
  font-weight: 650;
  color: var(--el-text-color-primary);
}
.cat-count {
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.comp-name {
  font-weight: 600;
}
.caps {
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.field-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.detail-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.detail-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.db-head {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
}
.db-title {
  font-size: 13px;
  font-weight: 650;
  color: var(--el-text-color-primary);
}
.db-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.feature-list {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
</style>
