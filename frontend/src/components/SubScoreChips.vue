<script setup lang="ts">
const props = defineProps<{
  scoreKeys: readonly string[]
  scores?: Record<string, number | null | undefined>
  labelOf: (key: string) => string
}>()

function roundedScore(key: string): number {
  return Math.round(props.scores?.[key] ?? 0)
}

function scoreLevel(key: string): string {
  const score = props.scores?.[key] ?? 0
  return score >= 80 ? 'hi' : score >= 50 ? 'mid' : 'lo'
}

</script>

<template>
  <div class="sub-score-chips">
    <span
      v-for="key in scoreKeys"
      :key="key"
      class="sub-score-chip"
      :class="scoreLevel(key)"
    >
      <span class="sub-score-chip__label">{{ labelOf(key) }}</span>
      <b>{{ roundedScore(key) }}</b>
    </span>
  </div>
</template>

<style scoped>
.sub-score-chips {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  gap: var(--app-space-control-gap);
}

.sub-score-chip {
  display: block;
  overflow: hidden;
  min-width: 0;
  max-width: 100%;
  padding: 2px 7px;
  border-radius: 11px;
  box-sizing: border-box;
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-comfy);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sub-score-chip__label {
  color: var(--el-text-color-secondary);
}

.sub-score-chip b {
  display: inline-block;
  margin-inline-start: var(--app-space-control-gap);
  font-variant-numeric: tabular-nums;
}

.sub-score-chip.hi {
  background: var(--score-high-bg);
}

.sub-score-chip.hi b {
  color: var(--score-high-text);
}

.sub-score-chip.mid {
  background: var(--score-mid-bg);
}

.sub-score-chip.mid b {
  color: var(--score-mid-text);
}

.sub-score-chip.lo {
  background: var(--el-fill-color);
}

.sub-score-chip.lo b {
  color: var(--el-text-color-secondary);
}
</style>
