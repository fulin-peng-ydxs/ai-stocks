export interface CssVariableSource { file: string; source: string }
export interface CssVariableReference { name: string; fallback: boolean; index: number }
export function cssVariableReferences(value: string): CssVariableReference[]
export function auditCssVariables(sources: CssVariableSource[], externalSources?: CssVariableSource[]): string[]
export function auditCssVariablesTree(): string[]
