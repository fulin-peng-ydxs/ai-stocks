import type { ComponentKind } from './schema'

export interface CompositeComponentSlotContract {
  id: string
  kind: ComponentKind
  parentId?: string
  requiredFields: string[]
}

export interface CompositeComponentContract {
  componentName: string
  sourcePath: string
  pageKeyAttribute: string
  slots: CompositeComponentSlotContract[]
  consumerRuntimeSources: string[]
  forbiddenComponentSources: string[]
}

/**
 * 封装多个可配置 slot 或业务口径的复合组件契约。
 * pageRegistry.spec 从真实 Vue 消费点反查本表，避免整个 slot 或业务偏好漏登记后
 * 因未进入正向检查集合而静默通过。
 */
export const COMPOSITE_COMPONENT_CONTRACTS: CompositeComponentContract[] = [
  {
    componentName: 'RankedStockWorkbench',
    sourcePath: 'components/ranked-stock/RankedStockWorkbench.vue',
    pageKeyAttribute: 'registry-page-key',
    slots: [
      {
        id: 'workspace',
        kind: 'master-detail',
        requiredFields: ['masterRatio', 'masterRatioProfiles'],
      },
      {
        id: 'result',
        kind: 'wide-table',
        parentId: 'workspace',
        requiredFields: ['border', 'defaultSort', 'hiddenColumns'],
      },
      {
        id: 'analysis',
        kind: 'chart',
        parentId: 'workspace',
        requiredFields: ['stockChart'],
      },
    ],
    consumerRuntimeSources: [
      ':component-runtime-value-of="componentRuntimeValueOf"',
      "tableBorder('result')",
      "componentValueOf('workspace', 'masterRatio')",
      "componentValueOf('workspace', 'masterRatioProfiles')",
    ],
    forbiddenComponentSources: ['adjust-mode="qfq"', "adjust-mode='qfq'"],
  },
]
