export interface TypographyAuditResult {
  files: number
  declarations: number
  violations: string[]
}
export function auditTypography(sources: Array<{ file: string; source: string }>): TypographyAuditResult
export function auditTypographyTree(root?: string): TypographyAuditResult
