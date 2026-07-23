import { createApp, defineComponent, h, ref } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '@/styles/global.css'
import type { Bar, IndicatorRow } from '@/api/stocks'
import StockChartWorkspace from '@/components/stock-chart/StockChartWorkspace.vue'
import type { AuxiliaryChartType } from '@/composables/useStockChartPreferences'
import { toggleTheme, useTheme } from '@/composables/useTheme'

const bars: Bar[] = Array.from({ length: 100 }, (_, index) => {
  const close = 10 + Math.sin(index / 8) * 1.4 + index * 0.025
  const open = close + Math.sin(index / 3) * 0.24
  return {
    date: `2026-${String(Math.floor(index / 28) + 4).padStart(2, '0')}-${String(index % 28 + 1).padStart(2, '0')}`,
    open,
    high: Math.max(open, close) + 0.35,
    low: Math.min(open, close) - 0.32,
    close,
    pre_close: index
      ? 10 + Math.sin((index - 1) / 8) * 1.4 + (index - 1) * 0.025
      : close,
    volume: 1_200_000 + Math.sin(index / 5) * 520_000 + index * 8_000,
    amount: 18_000_000,
    turnover_rate: 2.1,
  }
})

const indicators: IndicatorRow[] = bars.map((bar, index) => {
  const diff = Math.sin((index - 20) / 10) * 0.32
  const dea = Math.sin((index - 24) / 11) * 0.24
  return {
    trade_date: bar.date,
    macd_diff: diff,
    macd_dea: dea,
    macd_hist: 2 * (diff - dea),
    macd_golden_cross: index === 35 || index === 82,
    macd_dead_cross: index === 58,
  }
})

const Preview = defineComponent({
  setup() {
    const slot2 = ref<AuxiliaryChartType>('volume')
    const slot3 = ref<AuxiliaryChartType>('macd')
    const ratios = ref([0.6, 0.2, 0.2])
    const macdState = ref<'ready' | 'error'>('ready')
    const { isDark } = useTheme()

    function setMode(mode: 'three' | 'two' | 'one') {
      slot2.value = mode === 'one' ? 'hidden' : 'volume'
      slot3.value = mode === 'three' ? 'macd' : 'hidden'
      ratios.value = mode === 'three' ? [0.6, 0.2, 0.2] : mode === 'two' ? [0.75, 0.25] : [1]
    }

    return () => h('main', { class: 'preview-shell' }, [
      h('div', { class: 'preview-controls', 'aria-label': '工作区回归控制' }, [
        h('button', { 'data-testid': 'mode-three', onClick: () => setMode('three') }, '三图'),
        h('button', { 'data-testid': 'mode-two', onClick: () => setMode('two') }, '两图'),
        h('button', { 'data-testid': 'mode-one', onClick: () => setMode('one') }, '单图'),
        h('button', { 'data-testid': 'theme-toggle', onClick: toggleTheme },
          isDark.value ? '切换白天' : '切换夜间'),
        h('button', {
          'data-testid': 'macd-error-toggle',
          onClick: () => {
            macdState.value = macdState.value === 'ready' ? 'error' : 'ready'
          },
        }, '切换 MACD 局部错误'),
        h('span', { 'data-testid': 'ratio' },
          ratios.value.map((value) => `${Math.round(value * 100)}%`).join(' · ')),
      ]),
      h(StockChartWorkspace, {
        bars,
        indicators,
        slot2: slot2.value,
        slot3: slot3.value,
        heightRatios: ratios.value,
        macdState: macdState.value,
        macdError: '回归夹具：MACD 请求失败，K线与量能继续可用',
        onRatioCommit: (next: number[]) => { ratios.value = next },
      }),
    ])
  },
})

const style = document.createElement('style')
style.textContent = `
  body { margin: 0; }
  .preview-shell {
    min-width: 0;
    min-height: 100vh;
    padding: 16px;
    box-sizing: border-box;
    background: var(--el-bg-color-page);
  }
  .preview-controls {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 12px;
    color: var(--el-text-color-primary);
  }
`
document.head.appendChild(style)

createApp(Preview).use(ElementPlus).mount('#app')
