import type { Component } from 'vue'
import * as EpIcons from '@element-plus/icons-vue'

const MENU_ICON_MAP = EpIcons as unknown as Record<string, Component>

export const MENU_ICON_NAMES = Object.keys(MENU_ICON_MAP).sort()

export function resolveMenuIcon(name: string | null | undefined): Component | null {
  return name ? (MENU_ICON_MAP[name] ?? null) : null
}
