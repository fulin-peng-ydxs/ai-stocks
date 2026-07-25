import { computed, type ComputedRef } from 'vue'
import { useTheme } from '@/composables/useTheme'
import { useLayoutPreset } from '@/layout/useLayoutPreset'

export interface EChartsTheme {
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

/** 非股票 ECharts 的语义主题；只读取预设系统已经提交完成的 CSS token。 */
export function echartsTheme(isDark: boolean): EChartsTheme {
  return {
    background: chartCssVariable('--el-bg-color', isDark ? '#0b0e16' : '#ffffff'),
    axis: chartCssVariable('--el-border-color', isDark ? '#2b3550' : '#dcdfe6'),
    split: chartCssVariable('--el-border-color-lighter', isDark ? '#161c28' : '#ebeef5'),
    label: chartCssVariable('--el-text-color-secondary', isDark ? '#8b94a7' : '#909399'),
    text: chartCssVariable('--el-text-color-primary', isDark ? '#c9d1d9' : '#303133'),
    tooltipBackground: chartCssVariable(
      '--el-bg-color-overlay',
      isDark ? 'rgba(13,17,26,0.96)' : 'rgba(255,255,255,0.96)',
    ),
    tooltipBorder: chartCssVariable('--el-border-color', isDark ? '#2b3550' : '#dcdfe6'),
    focus: chartCssVariable('--el-color-primary', '#409eff'),
    accent: chartCssVariable('--el-color-warning', '#e6a23c'),
    muted: chartCssVariable('--el-text-color-placeholder', isDark ? '#687386' : '#a8abb2'),
    area: chartCssVariable(
      '--el-color-primary-light-9',
      isDark ? 'rgba(64,158,255,0.18)' : 'rgba(64,158,255,0.10)',
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
