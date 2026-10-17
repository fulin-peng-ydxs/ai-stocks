import { cloneVNode, defineComponent, h, watch, type Component, type PropType, type VNode } from 'vue'
import { ElPopover, ElTooltip } from 'element-plus'
import { useHoverIntent } from '@/composables/useHoverIntent'

/** 为 Element Plus 提示和富内容浮层提供同一套悬浮意图判定。 */
export default defineComponent({
  name: 'AppHoverInfo',
  inheritAttrs: false,
  props: {
    kind: { type: String as () => 'tooltip' | 'popover', default: 'tooltip' },
    disabled: { type: Boolean, default: false },
    reference: { type: Object as PropType<HTMLElement>, default: undefined },
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
      onPointerdownCapture: intent.onPointerDown,
      onKeydownCapture: intent.onKeyDown,
    }
    // 虚拟锚点让图标按钮保留真实 button 根节点，避免布局和权限指令穿透发生变化。
    watch(() => props.reference, (element, _, onCleanup) => {
      if (!element) return
      const events: Array<[string, EventListener, boolean?]> = [
        ['mouseenter', intent.onMouseEnter], ['mousemove', intent.onMouseMove],
        ['mouseleave', intent.onMouseLeave], ['focusin', intent.onFocusIn],
        ['focusout', event => intent.onFocusOut(event as FocusEvent)],
        ['pointerdown', intent.onPointerDown, true],
        ['keydown', event => intent.onKeyDown(event as KeyboardEvent), true],
        ['click', intent.onReferenceClick, true],
      ]
      for (const [name, handler, capture] of events) element.addEventListener(name, handler, capture)
      onCleanup(() => {
        for (const [name, handler, capture] of events) element.removeEventListener(name, handler, capture)
        intent.onReferenceClick()
      })
    }, { immediate: true, flush: 'post' })
    const contentEvents = {
      onMouseenter: intent.onContentEnter,
      onMouseleave: intent.onContentLeave,
    }
    const cloneSlot = (nodes: VNode[] | undefined, events: typeof referenceEvents | typeof contentEvents) =>
      nodes?.map((node) => cloneVNode(node, events, true)) ?? []

    return () => {
      if (props.disabled) {
        const nodes = (props.kind === 'popover' ? slots.reference : slots.default)?.()
        return nodes?.length === 1 ? nodes[0] : nodes ?? null
      }
      const popover = props.kind === 'popover'
      const component = (popover ? ElPopover : ElTooltip) as Component
      return h(component, {
        popperClass: 'app-wrapping-popper',
        ...attrs,
        disabled: props.disabled,
        visible: intent.visible.value,
        trigger: ['hover', 'focus'],
        showAfter: 0,
        ...(props.reference ? { virtualTriggering: true, virtualRef: props.reference } : {}),
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
