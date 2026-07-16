export type AppRowActionType = 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'info'

export type AppRowActionPlacement = 'auto' | 'inline' | 'more'

export interface AppRowAction {
  key: string
  label: string
  testId?: string
  type?: AppRowActionType
  permission?: string | string[]
  visible?: boolean
  disabled?: boolean
  loading?: boolean
  title?: string
  placement?: AppRowActionPlacement
  onClick?: (event?: MouseEvent) => void
}
