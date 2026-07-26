export interface PermNode {
  key: string
  code?: string
  label: string
  kind: 'menu' | 'resource'
  nodeType: string
  sysLocked: boolean
  baselineLocked?: boolean
  children?: PermNode[]
}
