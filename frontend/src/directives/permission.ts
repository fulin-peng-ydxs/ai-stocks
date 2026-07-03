// v-permission 按钮级权限指令（多租户 RBAC stage3·T15）。
// 用法：v-permission="'user:create'" 或 v-permission="['user:create','user:update']"（多码取并）。
// 无权则从 DOM 移除元素（不仅隐藏）——system 恒过，其余按 /me 下发的 permissions 判定。
// 说明：权限随会话稳定（变更走 perm_ver→401→重登→整页重载刷新），故 mounted 时判定并移除即可。
import type { Directive, DirectiveBinding } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'

function evaluate(el: HTMLElement, binding: DirectiveBinding<string | string[]>) {
  const auth = useAuthStore()
  if (!hasPermission(auth.role, auth.permissions, binding.value)) {
    el.parentNode?.removeChild(el)
  }
}

export const permission: Directive<HTMLElement, string | string[]> = {
  mounted: evaluate,
}
