import type { LocationQueryRaw } from 'vue-router'
import { detailReturnLabel, trustedDetailReturnPath } from '@/utils/detailReturnNavigation'

/** 板块详情只接受已知业务列表作为返回来源，避免形成开放重定向。 */
export function trustedSectorReturnPath(value: unknown): string | undefined {
  const path = trustedDetailReturnPath(value)
  return path?.startsWith('/sectors') ? undefined : path
}

/** 所有“走势板块”入口共用同一详情地址结构，禁止消费组件各自拼 return_to。 */
export function sectorDetailLocation(boardCode: string, returnPath?: string) {
  const trustedReturnPath = trustedSectorReturnPath(returnPath)
  return {
    path: `/sectors/${encodeURIComponent(boardCode)}`,
    query: trustedReturnPath ? { return_to: trustedReturnPath } : undefined,
  }
}

/** 详情页返回按钮按可信来源展示明确文案，未识别来源统一回到板块行情。 */
export function sectorReturnLabel(value: unknown): string {
  const returnPath = trustedSectorReturnPath(value)
  return detailReturnLabel(returnPath, '返回板块行情')
}

/** 详情页显式返回：可信跨模块来源原路返回，否则恢复板块列表当前 Tab 现场。 */
export function sectorListLocation(value: unknown): {
  path: '/sectors'
  query: LocationQueryRaw
} | string {
  const returnPath = trustedSectorReturnPath(value)
  if (returnPath) return returnPath
  return { path: '/sectors', query: { restore: '1' } }
}
