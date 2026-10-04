import type { InjectionKey } from 'vue'
import type { ComponentSlotConfigMeta } from './componentConfig'

export const SEARCH_COMPONENT_VALUE: InjectionKey<(slotId: string, field: string) => unknown> = Symbol('search-component-value')
export const SEARCH_RUNTIME_META: InjectionKey<Record<string, ComponentSlotConfigMeta>> = Symbol('search-runtime-meta')
