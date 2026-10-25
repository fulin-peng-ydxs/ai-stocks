import { computed, shallowReactive, type Ref } from 'vue'

export interface SettingItemLayoutState {
  requested: () => 'stacked' | 'inline'
  switchOnly: Ref<boolean>
  cannotFit: Ref<boolean>
}

export interface SettingItemLayoutGroup {
  stacked: Readonly<Ref<boolean>>
  register: (item: SettingItemLayoutState) => () => void
}

export const SETTING_ITEM_LAYOUT_GROUP = Symbol('setting-item-layout-group')
export type SettingItemLayoutElement = HTMLElement & { [SETTING_ITEM_LAYOUT_GROUP]?: SettingItemLayoutGroup }

/** 最近的 SettingsGroup 独立协调直接事项，子组不向父组传播排版。 */
export function createSettingItemLayoutGroup(): SettingItemLayoutGroup {
  const items = shallowReactive(new Set<SettingItemLayoutState>())
  const group: SettingItemLayoutGroup = {
    stacked: computed(() => [...items].some(item => !item.switchOnly.value
      && (item.requested() === 'stacked' || item.cannotFit.value))),
    register(item) {
      items.add(item)
      return () => { items.delete(item) }
    },
  }
  return group
}

/** 用不可交互的临时副本测量同行容量，避免切到上下布局后反复误判、来回跳动。 */
export function measureSettingItemInlineWidth(root: HTMLElement): number {
  const probe = document.createElement('div')
  probe.setAttribute('aria-hidden', 'true')
  probe.inert = true
  Object.assign(probe.style, {
    position: 'absolute', visibility: 'hidden', pointerEvents: 'none',
    display: 'inline-flex', width: 'max-content', maxWidth: 'none',
    gap: 'var(--app-density-control-gap, var(--app-space-2))',
  })
  for (const selector of ['.psi-label-row', '.psi-control']) {
    const original = root.querySelector<HTMLElement>(`:scope > ${selector}`)
    if (!original) continue
    const copy = original.cloneNode(true) as HTMLElement
    copy.querySelectorAll('[id]').forEach(element => element.removeAttribute('id'))
    Object.assign(copy.style, { width: 'max-content', maxWidth: 'none', flex: 'none', display: 'inline-flex' })
    const label = copy.querySelector<HTMLElement>('.psi-label')
    if (label) Object.assign(label.style, { whiteSpace: 'nowrap', flex: 'none' })
    probe.appendChild(copy)
  }
  root.appendChild(probe)
  try { return probe.scrollWidth }
  finally { probe.remove() }
}
