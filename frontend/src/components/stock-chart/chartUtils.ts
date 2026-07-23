export interface StockChartTheme {
  background: string
  axis: string
  split: string
  label: string
  text: string
  tooltipBackground: string
  tooltipBorder: string
  up: string
  down: string
  diff: string
  dea: string
  focus: string
}

let workspaceGroupSequence = 0

/** 模块级递增，确保同一页面并存的多个工作区不会误连到同一 ECharts group。 */
export function nextStockChartWorkspaceGroupId(): string {
  workspaceGroupSequence += 1
  return `stock-chart-workspace-${workspaceGroupSequence}`
}

function cssVariable(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

export function stockChartTheme(isDark: boolean): StockChartTheme {
  return {
    background: cssVariable('--el-bg-color', isDark ? '#0b0e16' : '#ffffff'),
    axis: cssVariable('--el-border-color', isDark ? '#2b3550' : '#dcdfe6'),
    split: cssVariable('--el-border-color-lighter', isDark ? '#161c28' : '#ebeef5'),
    label: cssVariable('--el-text-color-secondary', isDark ? '#8b94a7' : '#909399'),
    text: cssVariable('--el-text-color-primary', isDark ? '#c9d1d9' : '#303133'),
    tooltipBackground: cssVariable(
      '--el-bg-color-overlay',
      isDark ? 'rgba(13,17,26,0.96)' : 'rgba(255,255,255,0.96)',
    ),
    tooltipBorder: cssVariable('--el-border-color', isDark ? '#2b3550' : '#dcdfe6'),
    up: cssVariable('--market-up-color', isDark ? '#ff6b6b' : '#ef4d4d'),
    down: cssVariable('--market-down-color', isDark ? '#45c486' : '#22b573'),
    diff: cssVariable('--el-color-warning', '#e6a23c'),
    dea: cssVariable('--el-color-primary', '#409eff'),
    focus: cssVariable('--el-color-primary', '#409eff'),
  }
}

/** 后向移动平均；暖机不足返回 null，不读取当日之后的数据。 */
export function movingAverage(values: number[], period: number): (number | null)[] {
  return values.map((_, index) => {
    if (index + 1 < period) return null
    let total = 0
    for (let cursor = index + 1 - period; cursor <= index; cursor += 1) {
      total += values[cursor]
    }
    return +(total / period).toFixed(2)
  })
}

export function formatAmount(yuan: number | null | undefined): string {
  if (yuan == null || !Number.isFinite(yuan)) return '--'
  if (yuan >= 1e8) return `${(yuan / 1e8).toFixed(2)}亿`
  if (yuan >= 1e4) return `${(yuan / 1e4).toFixed(0)}万`
  return yuan.toFixed(0)
}

export function formatVolume(shares: number | null | undefined): string {
  if (shares == null || !Number.isFinite(shares)) return '--'
  const lots = shares / 100
  if (lots >= 1e8) return `${(lots / 1e8).toFixed(2)}亿手`
  if (lots >= 1e4) return `${(lots / 1e4).toFixed(2)}万手`
  return `${lots.toFixed(0)}手`
}

export function formatChartNumber(value: number | null | undefined, digits = 2): string {
  return value == null || !Number.isFinite(value) ? '--' : value.toFixed(digits)
}
