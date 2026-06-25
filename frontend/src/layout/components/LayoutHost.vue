<script setup lang="ts">
/**
 * 布局宿主（M2 核心）：消费一份已校验的 PageLayout，产出 .v-page 外壳 + 操作区（固定）+ 主内容区，
 * 并按规范自动选择主内容区策略（grow / 整区滚动 / 混合成长区 / 重排多列）。
 *
 * 「由构造即合规」：页面只用具名插槽（slot.id）填内容、声明 schema，
 * 不再手写 .v-page/.v-grow/100vh 等类与高度——CSS/DOM 层红线（规范 §9）由本宿主统一兜住。
 * 开发期对传入布局做 assertLayout，不合规立即抛错（生产构建自动剔除该断言）。
 */
import { computed } from 'vue'
import { COMPONENT_CATALOG } from '../components'
import type { PageLayout, ScrollOwnership, SlotSpec } from '../schema'
import { assertLayout } from '../validator'
import VColumns from './VColumns.vue'
import VMixedGrow from './VMixedGrow.vue'

const props = defineProps<{ layout: PageLayout }>()

if (import.meta.env.DEV) assertLayout(props.layout)

const byOrder = (a: SlotSpec, b: SlotSpec) => (a.order ?? 0) - (b.order ?? 0)
// 多组件主区（mixed/columns）按 order 逐个具名放置；操作区与单组件主区走固定区域插槽（#action/#main）。
// 嵌套 slot（parentId，如 section 内承载的表）与 overlay 区只进入可寻址/配置模型，不参与顶层主流渲染，由父组件/页面自行渲染。
const mainSlots = computed(() => props.layout.slots.filter((s) => s.region === 'main' && !s.parentId).sort(byOrder))

const effScroll = (s: SlotSpec): ScrollOwnership => s.scroll ?? COMPONENT_CATALOG[s.component]?.defaultScroll ?? 'none'

/** 主内容区策略（对齐规范 §8 三选一 + §5 重排）。 */
type MainStrategy = 'grow' | 'scroll' | 'mixed' | 'columns'
const mainStrategy = computed<MainStrategy>(() => {
  const slots = mainSlots.value
  if (!slots.length) return 'scroll'
  if (props.layout.responsive.allowReflow && slots.length > 1) return 'columns'
  if (slots.length > 1) return slots.some((s) => s.growMain) ? 'mixed' : 'scroll'
  // 单组件：整区滚动型 → .v-scroll；否则当作要撑满的主表/主图 → .v-grow
  return effScroll(slots[0]) === 'region' ? 'scroll' : 'grow'
})
</script>

<template>
  <div class="v-page" :class="`lh-density-${layout.density}`">
    <slot name="action" />
    <div v-if="mainStrategy === 'grow'" class="v-grow">
      <slot name="main" />
    </div>
    <div v-else-if="mainStrategy === 'scroll' && mainSlots.length === 1" class="v-scroll">
      <slot name="main" />
    </div>
    <VMixedGrow v-else-if="mainStrategy === 'mixed'" :slots="mainSlots">
      <template v-for="s in mainSlots" #[s.id]>
        <slot :name="s.id" />
      </template>
    </VMixedGrow>
    <VColumns
      v-else-if="mainStrategy === 'columns'"
      :breakpoints="layout.responsive.breakpoints"
      :slots="mainSlots"
    >
      <template v-for="s in mainSlots" #[s.id]>
        <slot :name="s.id" />
      </template>
    </VColumns>
    <div v-else class="v-scroll">
      <slot name="main" />
    </div>
    <!-- 固定底部区（如多选批量条/购物车条）：随 .v-page 取自身高、不滚动，在主区之下。纯渲染槽，不入 schema（同 #overlays）。 -->
    <slot name="footer" />
    <slot name="overlays" />
  </div>
</template>
