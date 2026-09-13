const ELEMENT_PLUS_POPPER_CONTAINER_SELECTOR = "[id^='el-popper-container-']"

function moveElementPlusPopperContainers(appRoot: HTMLElement): void {
  for (const container of document.body.querySelectorAll<HTMLElement>(
    `:scope > ${ELEMENT_PLUS_POPPER_CONTAINER_SELECTOR}`,
  )) {
    appRoot.append(container)
  }
}

/**
 * Element Plus 默认把所有锚点浮层 Teleport 到 body 下的共享容器。应用画布使用
 * transform 缩放时，触发器与该容器会落入不同坐标系；对浮层本身二次 scale 又会让
 * Popper 的定位尺寸失真。把共享容器移入 #app，可让二者继承同一套缩放与坐标原点。
 */
export function installElementPlusPopperContainer(appRoot: HTMLElement): () => void {
  moveElementPlusPopperContainers(appRoot)

  const observer = new MutationObserver(() => moveElementPlusPopperContainers(appRoot))
  observer.observe(document.body, { childList: true })

  return () => observer.disconnect()
}
