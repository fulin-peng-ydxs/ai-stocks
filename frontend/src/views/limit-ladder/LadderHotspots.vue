<script setup lang="ts">
import { reactive } from 'vue'
import { ElButton } from 'element-plus'
import type { LimitLadderHotspot, LimitLadderHotspotType } from '@/api/limitLadder'

const props = defineProps<{
  hotspots: Record<LimitLadderHotspotType, LimitLadderHotspot[]>
  activeType: LimitLadderHotspotType | null
  activeKey: string | null
}>()
defineEmits<{ toggle: [type: LimitLadderHotspotType, key: string] }>()

const MAX_VISIBLE = 12
const expanded = reactive<Record<LimitLadderHotspotType, boolean>>({ industry: false, concept: false })

function visibleItems(kind: LimitLadderHotspotType): LimitLadderHotspot[] {
  const items = props.hotspots[kind]
  if (expanded[kind] || items.length <= MAX_VISIBLE) return items
  const visible = items.slice(0, MAX_VISIBLE)
  if (props.activeType !== kind || !props.activeKey || visible.some((item) => item.group_key === props.activeKey)) {
    return visible
  }
  const active = items.find((item) => item.group_key === props.activeKey)
  return active ? [...visible.slice(0, MAX_VISIBLE - 1), active] : visible
}
</script>

<template>
  <section class="ladder-hotspots" aria-label="天梯热点">
    <div v-for="kind in (['industry', 'concept'] as const)" :key="kind" class="ladder-hotspots__group">
      <strong>{{ kind === 'industry' ? '行业热点' : '概念热点' }}</strong>
      <div class="ladder-hotspots__chips">
        <ElButton
          v-for="item in visibleItems(kind)"
          :key="`${kind}-${item.group_key}`"
          class="ladder-hotspots__chip"
          :class="{ 'is-active': activeType === kind && activeKey === item.group_key }"
          :aria-pressed="activeType === kind && activeKey === item.group_key"
          :data-testid="`limit-ladder-hotspot-${kind}-${item.group_key}`"
          @click="$emit('toggle', kind, item.group_key)"
        >
          <span>{{ item.group_name }}</span>
          <span class="ladder-hotspots__separator" aria-hidden="true">·</span>
          <b>{{ item.stock_count }}只</b>
        </ElButton>
        <span v-if="!hotspots[kind].length" class="ladder-hotspots__empty">暂无</span>
        <ElButton
          v-else-if="hotspots[kind].length > MAX_VISIBLE"
          class="ladder-hotspots__more"
          :aria-expanded="expanded[kind]"
          @click="expanded[kind] = !expanded[kind]"
        >{{ expanded[kind] ? '收起' : `展开其余 ${hotspots[kind].length - MAX_VISIBLE} 项` }}</ElButton>
      </div>
    </div>
  </section>
</template>

<style scoped>
.ladder-hotspots { display:grid; gap:var(--app-space-2); padding:var(--app-space-3) var(--app-space-4); border-bottom:1px solid var(--el-border-color-lighter); background:color-mix(in srgb,var(--el-fill-color-light) 45%,var(--el-bg-color)); }
.ladder-hotspots__group { display:grid; grid-template-columns:70px minmax(0,1fr); align-items:start; gap:var(--app-space-2); }
.ladder-hotspots__group>strong { padding-top:5px; color:var(--el-text-color-secondary); font-size:var(--app-font-size-caption); }
.ladder-hotspots__chips { display:flex; flex-wrap:wrap; gap:var(--app-space-1); }
.ladder-hotspots__chip { display:inline-flex; align-items:center; gap:var(--app-space-control-gap); min-height:28px; margin:0; padding:0 var(--app-space-2); border:1px solid var(--el-border-color); border-radius:999px; background:var(--el-bg-color); color:var(--el-text-color-regular); cursor:pointer; }
.ladder-hotspots__separator { color:var(--el-border-color-darker); }
.ladder-hotspots__chip b { color:var(--el-text-color-secondary); font-size:var(--app-font-size-caption); font-variant-numeric:tabular-nums; }
.ladder-hotspots__chip:hover,.ladder-hotspots__chip.is-active { border-color:var(--el-color-primary); color:var(--el-color-primary); }
.ladder-hotspots__chip.is-active { background:var(--el-color-primary-light-9); }
.ladder-hotspots__chip:focus-visible { outline:2px solid var(--el-color-primary); outline-offset:2px; }
.ladder-hotspots__empty { color:var(--app-placeholder-text); font-size:var(--app-font-size-caption); }
.ladder-hotspots__more { min-height:28px; margin:0; padding:0 var(--app-space-1); border:0; background:transparent; color:var(--el-color-primary); cursor:pointer; }
.ladder-hotspots__more:hover { text-decoration:underline; }
.ladder-hotspots__more:focus-visible { outline:2px solid var(--el-color-primary); outline-offset:2px; }
@media (max-width:720px) { .ladder-hotspots__group { grid-template-columns:1fr; } }
</style>
