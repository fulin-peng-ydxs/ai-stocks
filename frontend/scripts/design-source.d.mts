export interface Source { file: string; source: string }
export function auditComponentEntries(sources: Source[]): string[]
export function designSources(root?: string): Source[]
export const frontendRoot: string
export const designContracts: {
  entryPoints: Record<string, {owner: string | null; replacement: string}>
  styleRoles: Array<{className: string; properties: string[]; descendants?: boolean}>
  listStates: Array<{name: string; selector: string; declarations: Record<string, string>; forbidden?: string[]; media?: string}>
  listTokens: Record<string, string>
}
