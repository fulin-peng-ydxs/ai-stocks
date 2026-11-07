import type { Source } from './design-source.mjs'

/** 提取生产 Vue 样式中的容器与媒体查询。 */
export function responsiveQueries(file: string, source: string): string[]

/** 生成自动列并检查人工说明；不修改输入或写入文件。 */
export function syncResponsiveInventory(document: string, sources: Source[]): {
  document: string
  violations: string[]
}
