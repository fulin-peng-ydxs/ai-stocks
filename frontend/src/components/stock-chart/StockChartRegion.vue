<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useSlots, watch } from 'vue'
import type { AuxiliaryChartType, ChartType } from '@/composables/useStockChartPreferences'
import { stockChartWorkspaceMinHeight } from './workspaceOptions'

const props = withDefaults(defineProps<{
  totalHeight: number
  slot2?: AuxiliaryChartType
  slot3?: AuxiliaryChartType
  grow?: boolean
  ariaLabel?: string
}>(), {
  slot2: 'volume',
  slot3: 'macd',
  grow: false,
  ariaLabel: '股票图表区域',
})

defineSlots<{
  header?: () => unknown
  default: (props: { contentHeight: number }) => unknown
}>()

const slots = useSlots()
const rootEl = ref<HTMLElement | null>(null)
const headerEl = ref<HTMLElement | null>(null)
const bodyEl = ref<HTMLElement | null>(null)
const headerHeight = ref(0)
const frameHeight = ref(0)
const measuredContentHeight = ref(0)
let resizeObserver: ResizeObserver | null = null

const visibleTypes = computed<ChartType[]>(() => {
  const types: ChartType[] = ['kline']
  if (props.slot2 !== 'hidden') types.push(props.slot2)
  if (props.slot3 !== 'hidden') types.push(props.slot3)
  return types
})
const workspaceFloor = computed(() => stockChartWorkspaceMinHeight(visibleTypes.value))
const configuredHeight = computed(() => {
  const value = Number(props.totalHeight)
  return Number.isFinite(value) && value > 0 ? value : workspaceFloor.value
})
const effectiveTotalHeight = computed(() => Math.max(
  configuredHeight.value,
  workspaceFloor.value + headerHeight.value + frameHeight.value,
))
const contentHeight = computed(() => Math.max(
  workspaceFloor.value,
  measuredContentHeight.value || effectiveTotalHeight.value - headerHeight.value - frameHeight.value,
))

function measure(): void {
  const root = rootEl.value
  const header = headerEl.value
  const body = bodyEl.value
  headerHeight.value = Math.max(0, header?.offsetHeight ?? 0)
  frameHeight.value = root ? Math.max(0, root.offsetHeight - root.clientHeight) : 0
  const measured = body?.clientHeight ?? 0
  measuredContentHeight.value = measured > 0 ? measured : 0
}

function handleWindowResize(): void {
  measure()
}

onMounted(async () => {
  await nextTick()
  measure()
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(measure)
    if (rootEl.value) resizeObserver.observe(rootEl.value)
    if (headerEl.value) resizeObserver.observe(headerEl.value)
    if (bodyEl.value) resizeObserver.observe(bodyEl.value)
  } else {
    window.addEventListener('resize', handleWindowResize)
  }
})

watch(
  () => [props.totalHeight, props.slot2, props.slot3],
  () => nextTick(measure),
)

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  window.removeEventListener('resize', handleWindowResize)
})
</script>

<template>
  <section
    ref="rootEl"
    class="stock-chart-region"
    :style="{
      flexBasis: `${effectiveTotalHeight}px`,
      flexGrow: grow ? 1 : 0,
      height: `${effectiveTotalHeight}px`,
      minHeight: `${effectiveTotalHeight}px`,
    }"
    :data-configured-height="configuredHeight"
    :data-effective-height="effectiveTotalHeight"
    :data-content-height="contentHeight"
    :aria-label="ariaLabel"
  >
    <div v-if="slots.header" ref="headerEl" class="stock-chart-region__header">
      <slot name="header" />
    </div>
    <div ref="bodyEl" class="stock-chart-region__body">
      <slot :content-height="contentHeight" />
    </div>
  </section>
</template>

<style scoped>
.stock-chart-region {
  box-sizing: border-box;
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  overflow: hidden;
}

.stock-chart-region__header {
  flex: 0 0 auto;
  min-width: 0;
}

.stock-chart-region__body {
  position: relative;
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
</style>
