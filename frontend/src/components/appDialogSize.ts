export const APP_DIALOG_WIDTHS = {
  compact: '420px',
  narrow: '440px',
  medium: '480px',
  large: '520px',
  xlarge: '560px',
  max: '640px',
  workspace: 'min(92cqw, 1200px)',
} as const

export type AppDialogSize = keyof typeof APP_DIALOG_WIDTHS

export function isAppDialogSize(value: unknown): value is AppDialogSize {
  return typeof value === 'string' && value in APP_DIALOG_WIDTHS
}
