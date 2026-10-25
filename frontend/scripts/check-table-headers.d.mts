export interface TableHeaderSource {
  file: string
  source: string
}

export function auditTableHeaders(sources: TableHeaderSource[]): string[]
export function auditTableHeaderTree(root?: string): string[]
