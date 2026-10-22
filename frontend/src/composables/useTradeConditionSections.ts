import { computed, nextTick, ref, watch } from 'vue'
import { useDefaultedSessionValue } from './useDefaultedSessionValue'
import { STOCK_CONDITION_DEFAULT_COLLAPSED, type StockConditionPanelDefaults } from '@/layout/configPanel'
import type { ConditionSection, ConditionSectionsState } from '@/utils/tradeDisciplineConditions'

/** 规则与核对共用折叠状态和错误定位；外层卡片卸载时由表单持有受控状态。 */
export function useTradeConditionSections(
  state: () => ConditionSectionsState | undefined,
  changed: (value: ConditionSectionsState) => void,
  defaults: () => StockConditionPanelDefaults | undefined = () => undefined,
) {
  const root = ref<HTMLElement>()
  const local = ref<ConditionSectionsState>({})
  const baseline = useDefaultedSessionValue(computed<ConditionSectionsState>(() => {
    const closed = defaults()?.defaultCollapsed ?? STOCK_CONDITION_DEFAULT_COLLAPSED
    return Object.fromEntries(STOCK_CONDITION_DEFAULT_COLLAPSED.map(key => [key, !closed.includes(key)]))
  }))
  // 远端默认晚到时只更新尚未操作的分区，不覆盖手动开合或校验定位。
  const open = computed(() => ({ ...baseline.value, ...(state() ?? local.value) }))
  watch(() => defaults()?.resetKey, () => {
    local.value = {}
    changed({})
  })
  function setOpen(section: ConditionSection, value: boolean) {
    local.value = { ...(state() ?? local.value), [section]: value }
    changed(local.value)
  }
  async function reveal(section: ConditionSection, itemId?: string) {
    setOpen(section, true)
    await nextTick()
    const group = root.value?.querySelector<HTMLElement>(`[data-condition-section="${section}"]`)
    const item = itemId ? Array.from(group?.querySelectorAll<HTMLElement>('[data-checklist-id]') ?? [])
      .find(element => element.dataset.checklistId === itemId) : undefined
    const target = item ?? group?.querySelector<HTMLElement>('.config-panel-section__body')
    target?.scrollIntoView?.({ block: 'nearest' })
    target?.querySelector<HTMLElement>('textarea:not([disabled]),input:not([disabled]),[tabindex="0"]')?.focus({ preventScroll: true })
  }
  return { root, open, setOpen, reveal }
}
