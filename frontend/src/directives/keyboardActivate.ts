import type { ObjectDirective } from 'vue'
import { acceptsKeyboardEvent, isKeyboardDisabled } from '@/utils/keyboard'

function activate(event: KeyboardEvent) {
  const element = event.currentTarget as HTMLElement
  if (event.target !== element || (event.key !== 'Enter' && event.key !== ' ')) return
  // 原生控件与 Element Plus 触发器已有键盘语义，禁止重复合成 click。
  if (element.matches('button, input, select, textarea, a[href]')) return
  if (!acceptsKeyboardEvent(event) || isKeyboardDisabled(element)) return
  event.preventDefault()
  event.stopPropagation()
  element.click()
}

/** 非原生命令入口复用现有 click；role、tabindex、名称及禁用态由宿主声明。 */
export const vKeyboardActivate: ObjectDirective<HTMLElement> = {
  mounted: element => element.addEventListener('keydown', activate),
  beforeUnmount: element => element.removeEventListener('keydown', activate),
}
