export interface PageBusinessPreferenceContract {
  key: string
  label: string
  prop: string
  defaultValueSource: string
  consumerComponents: string[]
  forbiddenLiteralValues: string[]
}

/**
 * 会影响业务结果或展示口径的页面偏好事实源。
 * 契约测试从真实组件消费点反查默认值、设置抽屉和运行时传参；新增业务口径必须先登记，
 * 不能只依赖 usePageSettings 对“已经声明的字段”做单向完整性检查。
 */
export const PAGE_BUSINESS_PREFERENCE_CONTRACTS: PageBusinessPreferenceContract[] = [
  {
    key: 'adjustMode',
    label: '复权模式',
    prop: 'adjust-mode',
    defaultValueSource: "adjustMode: 'qfq'",
    consumerComponents: ['StockAnalysisPanel', 'RankedStockWorkbench'],
    forbiddenLiteralValues: ['', 'qfq', 'hfq'],
  },
]
