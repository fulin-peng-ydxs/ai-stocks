<script setup lang="ts">
import { formatNumber } from '@/utils/numberFormat'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, watch } from 'vue'
import { ElButton } from 'element-plus'
import type { LimitLadderHotspot, LimitLadderHotspotType } from '@/api/limitLadder'
import AppHoverInfo from '@/components/AppHoverInfo'
import AppStatusDot from '@/components/AppStatusDot.vue'
import { fitHotspotRow } from './hotspotRow'

const props = defineProps<{
  hotspots: Record<LimitLadderHotspotType, LimitLadderHotspot[]>
  activeType: LimitLadderHotspotType | null
  activeKey: string | null
}>()
defineEmits<{ toggle: [type: LimitLadderHotspotType, key: string] }>()

const kinds = ['industry', 'concept'] as const
const expanded = reactive<Record<LimitLadderHotspotType, boolean>>({ industry: false, concept: false })
const roots: Partial<Record<LimitLadderHotspotType, HTMLElement>> = {}
const measurements = reactive(Object.fromEntries(kinds.map(kind => [kind, {
  widths: {} as Record<string, number>, width: 0, moreWidth: 0, gap: 0, rowHeight: 0, height: 0,
}])) as Record<LimitLadderHotspotType, {
  widths: Record<string, number>; width: number; moreWidth: number; gap: number; rowHeight: number; height: number
}>)
const layouts = computed(() => Object.fromEntries(kinds.map(kind => {
  const measured = measurements[kind]
  return [kind, fitHotspotRow(props.hotspots[kind].map(item => item.group_key),
    measured.widths, measured.width, measured.moreWidth, measured.gap,
    props.activeType === kind ? props.activeKey : null)]
})) as Record<LimitLadderHotspotType, ReturnType<typeof fitHotspotRow>>)

function orderedItems(kind: LimitLadderHotspotType): LimitLadderHotspot[] {
  const items = new Map(props.hotspots[kind].map(item => [item.group_key, item]))
  return layouts.value[kind].keys.map(key => items.get(key)!)
}

function viewportHeight(kind: LimitLadderHotspotType): string | undefined {
  const measured = measurements[kind]
  const height = expanded[kind] ? measured.height : measured.rowHeight
  return height > 0 ? `${height}px` : undefined
}

function measure(): void {
  for (const kind of kinds) {
    const root = roots[kind]
    if (!root || root.clientWidth <= 0) continue
    const chips = root.querySelector<HTMLElement>('.ladder-hotspots__chips')!
    const buttons = Array.from(chips.querySelectorAll<HTMLElement>('.ladder-hotspots__chip'))
    const more = root.querySelector<HTMLElement>('.ladder-hotspots__disclosure')!
    measurements[kind] = {
      widths: Object.fromEntries(buttons.map(button => [button.dataset.hotspotKey!, button.offsetWidth])),
      width: root.clientWidth,
      moreWidth: more.offsetWidth,
      gap: parseFloat(getComputedStyle(chips).columnGap) || 0,
      rowHeight: buttons[0]?.offsetHeight ?? chips.offsetHeight,
      height: chips.offsetHeight,
    }
  }
}
let observer: ResizeObserver | undefined
onMounted(() => {
  measure()
  if (typeof ResizeObserver === 'undefined') return
  observer = new ResizeObserver(measure)
  for (const root of Object.values(roots)) {
    observer.observe(root)
    observer.observe(root.querySelector('.ladder-hotspots__chips')!)
    observer.observe(root.querySelector('.ladder-hotspots__disclosure')!)
  }
})
watch(() => [props.hotspots, props.activeType, props.activeKey], () => nextTick(measure), { deep: true })
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <section class="ladder-hotspots" aria-label="天梯热点">
    <div v-for="kind in kinds" :key="kind" class="ladder-hotspots__group">
      <strong>{{ kind === 'industry' ? '行业热点' : '概念热点' }}</strong>
      <div :ref="el => { if (el) roots[kind] = el as HTMLElement }" class="ladder-hotspots__body">
        <div
          :id="`ladder-hotspots-${kind}`"
          class="ladder-hotspots__viewport"
          :style="{ height: viewportHeight(kind) }"
        >
          <div class="ladder-hotspots__chips">
            <AppHoverInfo
              v-for="(item, index) in orderedItems(kind)"
              :key="`${kind}-${item.group_key}`"
              :disabled="!item.historical_stock_count"
              :content="`其中 ${formatNumber(item.historical_stock_count, 'count')} 只股票因当日共同有效样本不足，沿用此前最近有效结果`"
              placement="top"
              popper-class="app-wrapping-popper"
            >
              <ElButton
                class="ladder-hotspots__chip app-interaction-choice"
                :data-hotspot-key="item.group_key"
                :inert="!expanded[kind] && index >= layouts[kind].count ? true : undefined"
                :aria-hidden="!expanded[kind] && index >= layouts[kind].count ? true : undefined"
                :aria-pressed="activeType === kind && activeKey === item.group_key"
                :data-testid="`limit-ladder-hotspot-${kind}-${item.group_key}`"
                @click="$emit('toggle', kind, item.group_key)"
              >
                <span class="ladder-hotspots__name">{{ item.group_name }}</span>
                <span class="ladder-hotspots__separator" aria-hidden="true">·</span>
                <b>{{ formatNumber(item.stock_count, 'count') }}只</b>
                <AppStatusDot v-if="item.historical_stock_count" :label="`含历史结果 ${formatNumber(item.historical_stock_count, 'count')} 只`" />
              </ElButton>
            </AppHoverInfo>
            <span v-if="!hotspots[kind].length" class="ladder-hotspots__empty">暂无</span>
          </div>
        </div>
        <div class="ladder-hotspots__disclosure" :class="{ 'is-unneeded': hotspots[kind].length <= layouts[kind].count }">
          <span aria-hidden="true">展开其余 {{ formatNumber(hotspots[kind].length, 'count') }} 项</span>
          <ElButton
            v-if="hotspots[kind].length > layouts[kind].count"
            class="ladder-hotspots__more" type="primary" text
            :aria-controls="`ladder-hotspots-${kind}`"
            :aria-expanded="expanded[kind]"
            @click="expanded[kind] = !expanded[kind]"
          >{{ expanded[kind] ? '收起展开项' : `展开其余 ${formatNumber(hotspots[kind].length - layouts[kind].count, 'count')} 项` }}</ElButton>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.ladder-hotspots { --ladder-hotspot-height:calc(var(--app-density-control-height, var(--app-control-height-md)) - var(--app-space-2)); display:grid; gap:var(--app-space-2); padding:var(--app-space-3) var(--app-space-4); border-bottom:1px solid var(--el-border-color-lighter); background:color-mix(in srgb,var(--app-section-bg) 45%,var(--el-bg-color)); }
.ladder-hotspots__group { display:grid; grid-template-columns:70px minmax(0,1fr); align-items:start; gap:var(--app-space-2); }
.ladder-hotspots__group>strong { display:flex; align-items:center; min-height:var(--ladder-hotspot-height); color:var(--el-text-color-secondary); font-size:var(--app-font-size-caption); }
.ladder-hotspots__body { display:flex; align-items:start; gap:var(--app-space-1); min-width:0; position:relative; }
.ladder-hotspots__viewport { flex:1; min-width:0; height:var(--ladder-hotspot-height); overflow:hidden; transition:height var(--app-motion-collapse) var(--app-motion-ease); }
.ladder-hotspots__chips { display:flex; flex-wrap:wrap; gap:var(--app-space-1); }
.ladder-hotspots__chip { display:inline-flex; flex:none; max-width:100%; align-items:center; gap:var(--app-space-control-gap); min-height:var(--ladder-hotspot-height); margin:0; padding:0 var(--app-space-2); border:1px solid var(--el-border-color); border-radius:999px; background:var(--el-bg-color); color:var(--el-text-color-regular); cursor:pointer; }
/* 只提升高度声明的优先级，外观继续沿用原选择器及共享按钮配方。 */
.ladder-hotspots__chip.el-button,
.ladder-hotspots__more.el-button { height:var(--ladder-hotspot-height); }
.ladder-hotspots__chip :deep(>span) { min-width:0; }
.ladder-hotspots__name { min-width:0; overflow:hidden; text-overflow:ellipsis; }
.ladder-hotspots__separator { color:var(--el-border-color-darker); }
.ladder-hotspots__chip b { flex:none; color:var(--el-text-color-secondary); font-size:var(--app-font-size-caption); font-variant-numeric:tabular-nums; }
.ladder-hotspots__empty { color:var(--app-placeholder-text); font-size:var(--app-font-size-caption); }
.ladder-hotspots__disclosure { display:grid; flex:none; font-size:var(--app-button-font-size); font-weight:var(--app-button-font-weight); }
.ladder-hotspots__disclosure>span { grid-area:1/1; visibility:hidden; white-space:nowrap; padding:0 var(--app-space-control-gap); }
.ladder-hotspots__disclosure.is-unneeded { position:absolute; visibility:hidden; pointer-events:none; }
.ladder-hotspots__more { grid-area:1/1; justify-self:start; min-height:var(--ladder-hotspot-height); margin:0; padding:0 var(--app-space-1); }
@container app-viewport (max-width:720px) { .ladder-hotspots__group { grid-template-columns:1fr; } }
</style>
