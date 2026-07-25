import type { ComputedRef } from 'vue'
import { useResponsiveEChartsTheme } from '@/components/chartTheme'
import { stockChartTheme, type StockChartTheme } from './chartUtils'

/**
 * 股票画布主题的唯一响应式消费入口。
 * themeRevision 在整套 CSS token 写入后变化，保证调用方不会读取半更新主题。
 */
export function useStockChartTheme(): ComputedRef<StockChartTheme> {
  return useResponsiveEChartsTheme(stockChartTheme)
}
