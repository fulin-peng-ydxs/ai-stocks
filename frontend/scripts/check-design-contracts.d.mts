export interface Source { file: string; source: string }
export interface RuntimeStyleOwner {
  file: string
  operation: string
  target: string
  properties?: string[]
  expression?: string
  reason: string
}
export interface StyleRole {
  className: string
  classNames?: string[]
  properties: string[]
  descendants?: boolean
  tags?: string[]
  elementTag?: string
  innerTags?: string[]
  owners?: Array<{ file: string; selectors: string[]; properties: string[]; reason: string }>
  bindings?: Array<{ file: string; tag: string; name: string; expression: string; reason: string }>
  styleAttributes?: string[]
  within?: string
}
export function auditSharedStyles(sources: Source[], roles?: StyleRole[], options?: { verifyOwners?: boolean }): string[]
export function auditRuntimeStyles(sources: Source[], owners?: RuntimeStyleOwner[], options?: { verifyOwners?: boolean }): string[]
export function auditColorSources(sources: Source[], exceptions?: Array<{file: string; selector: string; property: string; value?: string; values?: string[]; reason: string}>): string[]
export function auditDesignStateContract(css: string, design: string): string[]
export function auditButtonKinds(sources: Source[]): string[]
export function auditButtonStates(css: string): string[]
export function auditDesignContracts(sources?: Source[], design?: string): string[]
export function renderDesignContract(): string
