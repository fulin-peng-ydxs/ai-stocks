export interface SurfaceAuditResult { files: number; violations: string[] }
export function auditSurfaces(sources: Array<{ file: string; source: string }>): SurfaceAuditResult
export function auditSurfaceTree(root?: string): SurfaceAuditResult
