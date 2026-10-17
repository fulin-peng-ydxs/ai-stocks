import { computed, type ComputedRef } from 'vue'
import { useTheme } from '@/composables/useTheme'
import { useLayoutPreset } from '@/layout/useLayoutPreset'

export interface EChartsTheme {
  typography: ChartTypography
  background: string
  axis: string
  split: string
  label: string
  text: string
  tooltipBackground: string
  tooltipBorder: string
  focus: string
  accent: string
  muted: string
  area: string
}

export function chartCssVariable(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

/** 图表文本适配：ECharts 需要数字字号，统一从 CSS 字阶取值，不在消费页另设尺度。 */
export function chartTypography() {
  const numberToken = (name: string, fallback: number) => {
    const value = Number.parseFloat(chartCssVariable(name, String(fallback)))
    return Number.isFinite(value) && value > 0 ? value : fallback
  }
  return {
    fontFamily: chartCssVariable('--app-font-family-base', 'system-ui, sans-serif'),
    axis: numberToken('--app-font-size-tiny', 10),
    compact: numberToken('--app-font-size-micro', 11),
    body: numberToken('--app-font-size-caption', 12),
    annotationLineHeight: numberToken('--app-line-height-ornament', 13),
    regular: numberToken('--app-font-weight-regular', 400),
    section: numberToken('--app-font-weight-section', 600),
    strong: numberToken('--app-font-weight-strong', 700),
  }
}
export type ChartTypography = ReturnType<typeof chartTypography>

/** KeepAlive、v-show 与布局切换期间禁止在 0×0 容器创建 ECharts 实例。 */
export function hasRenderableChartSize(element: HTMLElement): boolean {
  return element.clientWidth > 0 && element.clientHeight > 0
}

/** 非股票 ECharts 的语义主题；只读取预设系统已经提交完成的 CSS token。fallback 与 balanced 预设同值，避免预设未就绪时回退到旧色。 */
export function echartsTheme(isDark: boolean): EChartsTheme {
  return {
    typography: chartTypography(),
    background: chartCssVariable('--el-bg-color', isDark ? '#171717' : '#ffffff'),
    axis: chartCssVariable('--el-border-color', isDark ? '#353535' : '#e5e5e5'),
    split: chartCssVariable('--el-border-color-lighter', isDark ? '#353535' : '#e5e5e5'),
    label: chartCssVariable('--el-text-color-secondary', isDark ? '#9a9a9a' : '#73757d'),
    text: chartCssVariable('--el-text-color-primary', isDark ? '#f4f4f4' : '#17181c'),
    tooltipBackground: chartCssVariable(
      '--el-bg-color-overlay',
      isDark ? 'rgba(23,23,23,0.96)' : 'rgba(255,255,255,0.96)',
    ),
    tooltipBorder: chartCssVariable('--el-border-color', isDark ? '#353535' : '#e5e5e5'),
    focus: chartCssVariable('--el-color-primary', isDark ? '#3b8cff' : '#1677ff'),
    accent: chartCssVariable('--el-color-warning', isDark ? '#f5a623' : '#f58a07'),
    muted: chartCssVariable('--el-text-color-placeholder', isDark ? '#9a9a9a' : '#73757d'),
    area: chartCssVariable(
      '--el-color-primary-light-9',
      isDark ? 'rgba(59,140,255,0.18)' : 'rgba(22,119,255,0.10)',
    ),
  }
}

/**
 * Canvas 不会自动响应 CSS 变量；统一监听完整 token 提交后的修订号再重新取色。
 * 股票和普通 ECharts 入口共同复用，避免主题触发条件分叉。
 */
export function useResponsiveEChartsTheme<T>(
  factory: (isDark: boolean) => T,
): ComputedRef<T> {
  const { isDark } = useTheme()
  const { themeRevision } = useLayoutPreset()
  return computed(() => {
    void themeRevision.value
    return factory(isDark.value)
  })
}

export function useEChartsTheme(): ComputedRef<EChartsTheme> {
  return useResponsiveEChartsTheme(echartsTheme)
}

/**
 * 语义状态/金融色快照：供内联 style 的组件（评分热力、评级、买卖标记等）消费当前生效 token。
 * 与 Canvas 一致监听 themeRevision，预设/明暗切换后自动重取；fallback 与 balanced 预设同值。
 */
export interface StatusColorPalette {
  primary: string
  success: string
  warning: string
  danger: string
  marketUp: string
  marketDown: string
  muted: string
}

export function statusColorPalette(isDark: boolean): StatusColorPalette {
  return {
    primary: chartCssVariable('--el-color-primary', isDark ? '#3b8cff' : '#1677ff'),
    success: chartCssVariable('--el-color-success', isDark ? '#3ecf8e' : '#0ea968'),
    warning: chartCssVariable('--el-color-warning', isDark ? '#f5a623' : '#f58a07'),
    danger: chartCssVariable('--el-color-danger', isDark ? '#ff6b66' : '#f04438'),
    marketUp: chartCssVariable('--market-up-color', isDark ? '#ff7a72' : '#f66055'),
    marketDown: chartCssVariable('--market-down-color', isDark ? '#3fdd90' : '#1ec96e'),
    muted: chartCssVariable('--el-text-color-secondary', isDark ? '#9a9a9a' : '#73757d'),
  }
}

export function useStatusColorPalette(): ComputedRef<StatusColorPalette> {
  return useResponsiveEChartsTheme(statusColorPalette)
}
