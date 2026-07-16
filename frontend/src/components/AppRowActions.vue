<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { getActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import type { AppRowAction, AppRowActionType } from './rowActions'

const props = withDefaults(defineProps<{
  actions: AppRowAction[]
  inlineLimit?: number
  ariaLabel?: string
  emptyText?: string
  moreLabel?: string
}>(), {
  inlineLimit: 3,
  ariaLabel: '行操作',
  emptyText: '—',
  moreLabel: '更多',
})

const auth = getActivePinia() ? useAuthStore() : null
type ButtonRef = HTMLElement | { $el?: HTMLElement } | null
const moreButton = ref<ButtonRef>(null)
const menuEl = ref<HTMLElement | null>(null)
const menuOpen = ref(false)
const menuStyle = ref<Record<string, string>>({})
let listening = false

function isAllowed(action: AppRowAction): boolean {
  if (action.visible === false) return false
  if (!action.permission) return true
  if (!auth) return false
  return hasPermission(auth.role, auth.permissions, action.permission)
}

const visibleActions = computed(() => props.actions.filter(isAllowed))

const inlineActions = computed(() => {
  const limit = Math.max(0, props.inlineLimit)
  return visibleActions.value
    .filter((action) => action.placement !== 'more')
    .slice(0, limit)
})

const moreActions = computed(() => {
  const inlineKeys = new Set(inlineActions.value.map((action) => action.key))
  return visibleActions.value.filter((action) => (
    action.placement === 'more' || !inlineKeys.has(action.key)
  ))
})

function actionTone(action: AppRowAction, inlineIndex?: number): AppRowActionType {
  if (action.type) return action.type
  return inlineIndex === 0 ? 'primary' : 'default'
}

function actionClass(action: AppRowAction, inlineIndex?: number) {
  return [
    `is-tone-${actionTone(action, inlineIndex)}`,
    { 'is-loading': action.loading },
  ]
}

function runAction(action: AppRowAction, event?: MouseEvent): void {
  if (action.disabled || action.loading) return
  action.onClick?.(event)
}

function getAnchorEl(): HTMLElement | null {
  const raw = moreButton.value
  if (!raw) return null
  return raw instanceof HTMLElement ? raw : raw.$el ?? null
}

function positionMenu(): void {
  const anchor = getAnchorEl()
  if (!anchor) return
  const rect = anchor.getBoundingClientRect()
  const width = Math.max(128, rect.width + 44)
  const viewportGap = 8
  const left = Math.min(
    window.innerWidth - width - viewportGap,
    Math.max(viewportGap, rect.right - width),
  )
  const belowTop = rect.bottom + 4
  const belowMaxHeight = window.innerHeight - belowTop - viewportGap
  const top = belowMaxHeight >= 96 ? belowTop : Math.max(viewportGap, rect.top - 4 - 180)
  const maxHeight = belowMaxHeight >= 96 ? belowMaxHeight : Math.max(96, rect.top - viewportGap)
  menuStyle.value = {
    top: `${Math.round(top)}px`,
    left: `${Math.round(left)}px`,
    minWidth: `${Math.round(width)}px`,
    maxHeight: `${Math.round(maxHeight)}px`,
  }
}

function addListeners(): void {
  if (listening) return
  document.addEventListener('click', onDocumentClick, true)
  document.addEventListener('keydown', onDocumentKeydown, true)
  window.addEventListener('resize', closeMenu, true)
  window.addEventListener('scroll', closeMenu, true)
  listening = true
}

function removeListeners(): void {
  if (!listening) return
  document.removeEventListener('click', onDocumentClick, true)
  document.removeEventListener('keydown', onDocumentKeydown, true)
  window.removeEventListener('resize', closeMenu, true)
  window.removeEventListener('scroll', closeMenu, true)
  listening = false
}

function openMenu(): void {
  if (!moreActions.value.length) return
  positionMenu()
  menuOpen.value = true
  addListeners()
  void nextTick(positionMenu)
}

function closeMenu(): void {
  menuOpen.value = false
  removeListeners()
}

function toggleMenu(event: MouseEvent): void {
  event.stopPropagation()
  if (menuOpen.value) closeMenu()
  else openMenu()
}

function onDocumentClick(event: MouseEvent): void {
  const target = event.target as Node | null
  const anchor = getAnchorEl()
  if (!target) return
  if (anchor?.contains(target) || menuEl.value?.contains(target)) return
  closeMenu()
}

function onDocumentKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') closeMenu()
}

function runMenuAction(action: AppRowAction, event: MouseEvent): void {
  event.stopPropagation()
  runAction(action, event)
  closeMenu()
}

onBeforeUnmount(removeListeners)
</script>

<template>
  <div class="app-row-actions" role="group" :aria-label="ariaLabel">
    <template v-if="visibleActions.length">
      <el-button
        v-for="(action, index) in inlineActions"
        :key="action.key"
        class="app-row-actions__button"
        :class="actionClass(action, index)"
        link
        size="small"
        :loading="action.loading"
        :disabled="action.disabled"
        :title="action.title"
        @click.stop="runAction(action, $event)"
      >
        {{ action.label }}
      </el-button>
      <span v-if="moreActions.length" class="app-row-actions__more-wrap">
        <el-button
          ref="moreButton"
          class="app-row-actions__button app-row-actions__more"
          :class="{ 'is-open': menuOpen }"
          link
          size="small"
          :aria-expanded="menuOpen"
          aria-haspopup="menu"
          @click="toggleMenu"
        >
          {{ moreLabel }}
          <el-icon class="app-row-actions__more-icon"><ArrowDown /></el-icon>
        </el-button>
      </span>
    </template>
    <span v-else class="app-row-actions__empty">{{ emptyText }}</span>
    <Teleport to="body">
      <div
        v-if="menuOpen"
        ref="menuEl"
        class="app-row-actions-menu"
        :style="menuStyle"
        role="menu"
        @click.stop
      >
        <button
          v-for="(action, index) in moreActions"
          :key="action.key"
          type="button"
          class="app-row-actions-menu__item"
          :class="actionClass(action)"
          :disabled="action.disabled || action.loading"
          :title="action.title"
          role="menuitem"
          @click="runMenuAction(action, $event)"
        >
          {{ action.label }}
        </button>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.app-row-actions {
  display: inline-flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: var(--app-space-2);
  max-width: 100%;
  min-width: 0;
  white-space: nowrap;
  vertical-align: middle;
}

.app-row-actions__button {
  --row-action-text: var(--el-text-color-regular);
  --row-action-hover-text: var(--el-text-color-primary);
  margin-left: 0 !important;
  min-height: 24px;
  padding: 0 5px !important;
  color: var(--row-action-text) !important;
  font-weight: var(--app-font-weight-section);
  transition: color 120ms ease;
}

.app-row-actions__button:hover,
.app-row-actions__button:focus-visible,
.app-row-actions__button.is-open {
  color: var(--row-action-hover-text) !important;
}

.app-row-actions__button.is-tone-primary {
  --row-action-text: var(--el-color-primary);
  --row-action-hover-text: var(--el-color-primary-light-3);
}

.app-row-actions__button.is-tone-success {
  --row-action-text: var(--el-color-success);
  --row-action-hover-text: var(--el-color-success-light-3);
}

.app-row-actions__button.is-tone-warning {
  --row-action-text: var(--el-color-warning);
  --row-action-hover-text: var(--el-color-warning-light-3);
}

.app-row-actions__button.is-tone-danger {
  --row-action-text: var(--el-color-danger);
  --row-action-hover-text: var(--el-color-danger-light-3);
}

.app-row-actions__button.is-tone-info {
  --row-action-text: var(--el-text-color-regular);
  --row-action-hover-text: var(--el-text-color-primary);
}

.app-row-actions__button.is-disabled,
.app-row-actions__button:disabled {
  color: var(--el-text-color-disabled) !important;
  background: transparent;
}

.app-row-actions__more-wrap {
  display: inline-flex;
}

.app-row-actions__more-icon {
  margin-left: 2px;
  font-size: var(--app-icon-size-xs);
}

.app-row-actions__empty {
  color: var(--el-text-color-secondary);
}

.app-row-actions-menu {
  position: fixed;
  z-index: 3000;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  overflow: auto;
  padding: 4px;
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-control-radius);
  background: var(--el-bg-color-overlay);
  box-shadow: var(--el-box-shadow-light);
}

.app-row-actions-menu__item {
  --row-action-menu-text: var(--el-text-color-regular);
  --row-action-menu-bg: var(--el-fill-color-light);
  width: 100%;
  min-height: 28px;
  padding: 0 10px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--row-action-menu-text);
  font: inherit;
  font-size: var(--app-font-size-body);
  text-align: left;
  cursor: pointer;
}

.app-row-actions-menu__item:hover,
.app-row-actions-menu__item:focus-visible {
  outline: none;
  background: var(--row-action-menu-bg);
}

.app-row-actions-menu__item.is-tone-primary {
  --row-action-menu-text: var(--el-color-primary);
  --row-action-menu-bg: var(--el-color-primary-light-9);
}

.app-row-actions-menu__item.is-tone-success {
  --row-action-menu-text: var(--el-color-success);
  --row-action-menu-bg: var(--el-color-success-light-9);
}

.app-row-actions-menu__item.is-tone-warning {
  --row-action-menu-text: var(--el-color-warning);
  --row-action-menu-bg: var(--el-color-warning-light-9);
}

.app-row-actions-menu__item.is-tone-danger {
  --row-action-menu-text: var(--el-color-danger);
  --row-action-menu-bg: var(--el-color-danger-light-9);
}

.app-row-actions-menu__item.is-tone-info {
  --row-action-menu-text: var(--el-text-color-regular);
  --row-action-menu-bg: var(--el-fill-color-light);
}

.app-row-actions-menu__item:disabled {
  color: var(--el-text-color-disabled);
  cursor: not-allowed;
}

.app-row-actions-menu__item.is-loading {
  cursor: wait;
}
</style>
