const ELEMENT_PLUS_POPPER_CONTAINER_SELECTOR = "[id^='el-popper-container-']"
const PAGE_OVERLAY_SELECTOR = '.el-popper, .el-overlay'
const DENSITY_VARIABLES = [
  '--app-density-page-gap',
  '--app-density-section-gap',
  '--app-density-card-padding',
  '--app-density-control-gap',
  '--app-density-form-gap',
  '--app-density-control-height',
  '--app-density-button-padding-x',
  '--app-density-table-cell-padding-y',
  '--app-density-overlay-padding',
  '--app-density-overlay-group-gap',
  '--layout-page-gap',
  '--layout-card-padding',
  '--layout-table-cell-padding-y',
] as const

function moveElementPlusPopperContainers(appRoot: HTMLElement): void {
  for (const container of document.body.querySelectorAll<HTMLElement>(
    `:scope > ${ELEMENT_PLUS_POPPER_CONTAINER_SELECTOR}`,
  )) {
    appRoot.append(container)
  }
}

function copyPageDensity(target: HTMLElement, source: HTMLElement | null): void {
  for (const variable of DENSITY_VARIABLES) {
    if (source) target.style.setProperty(variable, getComputedStyle(source).getPropertyValue(variable))
    else target.style.removeProperty(variable)
  }
}

function densitySource(lastInteractionTarget: Element | null): HTMLElement | null {
  const focused = document.activeElement instanceof Element ? document.activeElement : null
  return focused?.closest<HTMLElement>('.v-page')
    ?? lastInteractionTarget?.closest<HTMLElement>('.v-page')
    ?? null
}

function syncAddedOverlay(
  node: Node,
  lastInteractionTarget: Element | null,
  sources: Map<HTMLElement, HTMLElement>,
): void {
  if (!(node instanceof HTMLElement)) return
  const source = densitySource(lastInteractionTarget)
  const overlays = [
    ...(node.matches(PAGE_OVERLAY_SELECTOR) ? [node] : []),
    ...node.querySelectorAll<HTMLElement>(PAGE_OVERLAY_SELECTOR),
  ]
  for (const overlay of overlays) {
    // PageDrawer 本就挂在 LayoutHost 内，保留它自然继承的页面密度。
    if (!overlay.closest('.v-page')) {
      copyPageDensity(overlay, source)
      if (source) sources.set(overlay, source)
      else sources.delete(overlay)
    } else sources.delete(overlay)
  }
}

/**
 * Element Plus 默认把锚点浮层 Teleport 到 body 下的共享容器。把共享容器移入 #app，
 * 让触发器与浮层共同继承根画布的 zoom、页面密度和布局坐标系。
 */
export function installElementPlusPopperContainer(appRoot: HTMLElement): () => void {
  const densitySources = new Map<HTMLElement, HTMLElement>()
  const sourceObservers = new Map<HTMLElement, MutationObserver>()
  function syncDensityObservers() {
    for (const [overlay, source] of densitySources) {
      if (!overlay.isConnected || !source.isConnected) densitySources.delete(overlay)
    }
    const sources = new Set(densitySources.values())
    for (const [source, observer] of sourceObservers) {
      if (!sources.has(source)) {
        observer.disconnect()
        sourceObservers.delete(source)
      }
    }
    for (const source of sources) {
      if (sourceObservers.has(source)) continue
      // 只观察真实触发页，避免订阅整棵应用树的样式动画、图表和悬停变化。
      const observer = new MutationObserver(() => {
        for (const [overlay, page] of densitySources) {
          if (page === source) copyPageDensity(overlay, page)
        }
      })
      observer.observe(source, { attributes: true, attributeFilter: ['class', 'style'] })
      sourceObservers.set(source, observer)
    }
  }
  let lastInteractionTarget: Element | null = null
  const rememberInteractionTarget = (event: Event) => {
    lastInteractionTarget = event.target instanceof Element ? event.target : null
  }
  moveElementPlusPopperContainers(appRoot)
  appRoot.addEventListener('pointerdown', rememberInteractionTarget, true)
  appRoot.addEventListener('focusin', rememberInteractionTarget, true)

  const bodyObserver = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) syncAddedOverlay(node, lastInteractionTarget, densitySources)
    }
    moveElementPlusPopperContainers(appRoot)
    syncDensityObservers()
  })
  // body 只关心直接 Teleport 节点和新建的共享 Popper 容器，避免扫描应用整棵 DOM。
  bodyObserver.observe(document.body, { childList: true })
  const appObserver = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) syncAddedOverlay(node, lastInteractionTarget, densitySources)
    }
    syncDensityObservers()
  })
  // 共享 Popper 容器已在 #app 内，监听其后续追加内容；按新增节点增量处理。
  appObserver.observe(appRoot, { childList: true, subtree: true })

  return () => {
    bodyObserver.disconnect()
    appObserver.disconnect()
    densitySources.clear()
    for (const observer of sourceObservers.values()) observer.disconnect()
    sourceObservers.clear()
    appRoot.removeEventListener('pointerdown', rememberInteractionTarget, true)
    appRoot.removeEventListener('focusin', rememberInteractionTarget, true)
  }
}
