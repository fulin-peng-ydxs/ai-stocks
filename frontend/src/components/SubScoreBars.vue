<script setup lang="ts">
import { computed } from 'vue'
import { SCORE_DIMS, type SubScores } from '@/api/board'

const props = defineProps<{ sub: SubScores | null }>()

// 每个维度按各自满分归一成强弱比例 → 颜色（深绿强 → 黄中 → 橙/红弱）
function heatColor(r: number): string {
  if (r >= 0.85) return '#2e9e5b' // 强
  if (r >= 0.65) return '#5cb85c'
  if (r >= 0.45) return '#e0a030' // 中
  if (r >= 0.25) return '#e8833a'
  return '#d9534f' // 弱
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
  gap: 8px;
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
  gap: 5px;
  min-width: 132px;
}
.tip-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
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
