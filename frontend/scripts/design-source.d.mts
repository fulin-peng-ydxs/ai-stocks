export interface Source { file: string; source: string }
export interface StyleDelegate { tags: string[]; owner: string; reason: string }
export function inferStyleRoles(sources: Source[], roles?: import('./check-design-contracts.mjs').StyleRole[]): import('./check-design-contracts.mjs').StyleRole[]
export function auditComponentEntries(sources: Source[], inspect?: (name: string, file: string, line: number, root: boolean) => void): string[]
export function auditStyleComponents(sources: Source[], roles?: import('./check-design-contracts.mjs').StyleRole[], delegates?: StyleDelegate[], options?: {verifyRegistry?: boolean}): string[]
export function designSources(root?: string): Source[]
export const frontendRoot: string
export const designContracts: {
  entryPoints: Record<string, {owner: string | null; replacement: string}>
  styleRoles: import('./check-design-contracts.mjs').StyleRole[]
  styleDelegates: StyleDelegate[]
  runtimeStyleOwners: import('./check-design-contracts.mjs').RuntimeStyleOwner[]
  listStates: Array<{name: string; selector: string; declarations: Record<string, string>; forbidden?: string[]; media?: string}>
  listTokens: Record<string, string>
}
