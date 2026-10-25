export interface Source { file: string; source: string }
export interface StyleRole { className: string; properties: string[]; descendants?: boolean }
export function auditSharedStyles(sources: Source[], roles?: StyleRole[]): string[]
export function auditColorSources(sources: Source[], exceptions?: Array<{file: string; selector: string; property: string; value?: string; values?: string[]; reason: string}>): string[]
export function auditDesignStateContract(css: string, design: string): string[]
export function auditDesignContracts(sources?: Source[], design?: string): string[]
export function renderDesignContract(): string
