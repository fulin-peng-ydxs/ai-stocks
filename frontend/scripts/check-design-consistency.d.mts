export interface Source { file: string; source: string }
export interface ConsistencyException { file: string; selector: string; property: string; value: string; reason: string }
export const consistencyExceptions: ConsistencyException[]
export function auditHeadings(sources: Source[]): string[]
export function auditSpacingMotion(sources: Source[], exceptions?: ConsistencyException[], options?: { verifyExceptions?: boolean }): string[]
export function auditPrimaryActions(sources: Source[]): string[]
export function auditDateTimeConsumers(sources: Source[]): string[]
export function auditSharedStyleRecipes(sources: Source[]): string[]
export function auditDesignConsistency(sources: Source[], options?: { verifyExceptions?: boolean }): string[]
export function findStyleReuseCandidates(sources: Source[]): Array<Array<{ file: string; selector: string; line: number }>>
