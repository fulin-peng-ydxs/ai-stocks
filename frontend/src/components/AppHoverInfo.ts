import { cloneVNode, defineComponent, h, type Component, type VNode } from 'vue'
import { ElPopover, ElTooltip } from 'element-plus'
import { useHoverIntent } from '@/composables/useHoverIntent'

/** 为 Element Plus 提示和富内容浮层提供同一套悬浮意图判定。 */
export default defineComponent({
  name: 'AppHoverInfo',
  inheritAttrs: false,
  props: {
    kind: { type: String as () => 'tooltip' | 'popover', default: 'tooltip' },
    disabled: { type: Boolean, default: false },
  },
  setup(props, { attrs, slots }) {
    const intent = useHoverIntent(() => props.disabled, () => props.kind === 'popover')
    const referenceEvents = {
      onMouseenter: intent.onMouseEnter,
      onMousemove: intent.onMouseMove,
      onMouseleave: intent.onMouseLeave,
      onFocusin: intent.onFocusIn,
      onFocusout: intent.onFocusOut,
      onClickCapture: intent.onReferenceClick,
    }
    const contentEvents = {
      onMouseenter: intent.onContentEnter,
      onMouseleave: intent.onContentLeave,
    }
    const cloneSlot = (nodes: VNode[] | undefined, events: typeof referenceEvents | typeof contentEvents) =>
      nodes?.map((node) => cloneVNode(node, events, true)) ?? []

    return () => {
      const popover = props.kind === 'popover'
      const component = (popover ? ElPopover : ElTooltip) as Component
      return h(component, {
        ...attrs,
        disabled: props.disabled,
        visible: intent.visible.value,
        trigger: ['hover', 'focus'],
        showAfter: 0,
      }, popover
        ? {
            reference: () => cloneSlot(slots.reference?.(), referenceEvents),
            default: () => cloneSlot(slots.default?.(), contentEvents),
          }
        : {
            default: () => cloneSlot(slots.default?.(), referenceEvents),
            content: slots.content,
          })
    }
  },
})
