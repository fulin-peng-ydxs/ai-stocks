import type { InjectionKey } from 'vue'

/** 只由页面设置抽屉提供；共享分组在其他容器中仍由调用方控制生命周期。 */
export interface SettingsFoldPreferences {
  enabled: () => boolean
  isOpen: (key: string) => boolean | undefined
  setOpen: (key: string, open: boolean) => void
}

export const SETTINGS_FOLD_PREFERENCES: InjectionKey<SettingsFoldPreferences> = Symbol('settings-fold-preferences')
