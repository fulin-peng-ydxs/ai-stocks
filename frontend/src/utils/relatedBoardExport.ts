import type { StockRelatedBoards } from '@/types/relatedBoards'

/** 导出名称与真实来源日期，避免历史回退结果在文件中丢失状态。 */
export function relatedBoardExportValues(
  summary: StockRelatedBoards | null | undefined,
  boardType: 'industry' | 'concept',
): [string, string, string] {
  const board = summary?.unavailable_reason ? null : summary?.[boardType]
  if (!board) return ['', '', '无结果']
  return [
    board.name,
    board.history?.as_of_date ?? summary?.as_of_date ?? '',
    board.history ? '历史' : '当日',
  ]
}
