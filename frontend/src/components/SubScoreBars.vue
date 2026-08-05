<script setup lang="ts">
import { computed } from 'vue'
import { SCORE_DIMS, type SubScores } from '@/api/board'
import { useStatusColorPalette } from './chartTheme'

const props = defineProps<{ sub: SubScores | null }>()

// 强弱热力统一消费语义色板：强=金融跌绿/成功绿 → 中=警示橙 → 弱=危险红/金融涨红。
const palette = useStatusColorPalette()
function heatColor(r: number): string {
  const p = palette.value
  if (r >= 0.85) return p.marketDown // 强
  if (r >= 0.65) return p.success
  if (r >= 0.45) return p.warning // 中
  if (r >= 0.25) return p.danger
  return p.marketUp // 弱
}

const cells = computed(() =>
  SCORE_DIMS.map((d) => {
    const val = props.sub ? Number(props.sub[d.key] ?? 0) : 0
    const ratio = d.max ? val / d.max : 0
    return { ...d, val, ratio, color: heatColor(ratio) }
  }),
)
</script>

<template>
  <el-tooltip placement="right" :show-after="100" effect="dark">
    <template #content>
      <div class="tip">
        <div v-for="c in cells" :key="c.key" class="tip-row">
          <span class="tip-dot" :style="{ background: c.color }" />
          <span class="tip-label">{{ c.label }}</span>
          <span class="tip-val">{{ c.val }} / {{ c.max }}</span>
        </div>
      </div>
    </template>
    <div class="cells">
      <span v-for="c in cells" :key="c.key" class="cell" :style="{ background: c.color }" />
    </div>
  </el-tooltip>
</template>

<style scoped>
.cells {
  display: flex;
  gap: var(--app-space-2);
  cursor: help;
}
.cell {
  width: 26px;
  height: 18px;
  border-radius: 4px;
  flex-shrink: 0;
}
.tip {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-control-gap);
  min-width: 132px;
}
.tip-row {
  display: flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  font-size: var(--app-font-size-caption);
}
.tip-dot {
  width: 9px;
  height: 9px;
  border-radius: 2px;
  flex-shrink: 0;
}
.tip-label {
  flex: 1;
}
.tip-val {
  font-variant-numeric: tabular-nums;
}
</style>
