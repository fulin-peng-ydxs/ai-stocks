// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { installElementPlusPopperContainer } from '../elementPlusPopperContainer'

const cleanups: Array<() => void> = []

afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup())
  document.body.innerHTML = ''
})

describe('Element Plus Popper 缩放容器', () => {
  it('应用抽屉内的浮层优先继承抽屉显式密度，并随其更新', async () => {
    document.body.innerHTML = `<div id="app">
      <main class="v-page" style="--app-density-overlay-padding:12px">
        <div class="el-drawer lh-density-comfortable" style="--app-density-overlay-padding:24px">
          <section class="page-drawer-surface"><button id="drawer-trigger">help</button></section>
        </div>
      </main>
    </div>`
    const root = document.querySelector<HTMLElement>('#app')!
    cleanups.push(installElementPlusPopperContainer(root))
    root.querySelector('#drawer-trigger')!.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    const popper = document.createElement('div')
    popper.className = 'el-popper'
    root.append(popper)
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(popper.style.getPropertyValue('--app-density-overlay-padding')).toBe('24px')
    root.querySelector<HTMLElement>('.el-drawer')!.style.setProperty('--app-density-overlay-padding', '16px')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(popper.style.getPropertyValue('--app-density-overlay-padding')).toBe('16px')
  })

  it('把已存在的共享容器移入应用根', () => {
    document.body.innerHTML = `
      <div id="app"></div>
      <div id="el-popper-container-test"><div class="el-popper"></div></div>
    `
    const appRoot = document.querySelector<HTMLElement>('#app')!

    cleanups.push(installElementPlusPopperContainer(appRoot))

    expect(appRoot.querySelector('#el-popper-container-test')).not.toBeNull()
    expect(document.body.querySelector(':scope > #el-popper-container-test')).toBeNull()
  })

  it('持续接管懒加载页面后续创建的共享容器', async () => {
    document.body.innerHTML = '<div id="app"></div>'
    const appRoot = document.querySelector<HTMLElement>('#app')!
    cleanups.push(installElementPlusPopperContainer(appRoot))

    const container = document.createElement('div')
    container.id = 'el-popper-container-lazy'
    document.body.append(container)
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(container.parentElement).toBe(appRoot)
  })

  it('不搬运 Element Plus 浮层以外的 body 节点', () => {
    document.body.innerHTML = '<div id="app"></div><div id="external-overlay"></div>'
    const appRoot = document.querySelector<HTMLElement>('#app')!

    cleanups.push(installElementPlusPopperContainer(appRoot))

    expect(document.querySelector('#external-overlay')?.parentElement).toBe(document.body)
  })

  it('页面触发的 Teleport 浮层同步继承当前页面密度', async () => {
    document.body.innerHTML = `
      <div id="app">
        <main class="v-page" style="--app-density-overlay-padding: 24px; --layout-table-cell-padding-y: 14px">
          <button id="page-trigger">open</button>
        </main>
      </div>
    `
    const appRoot = document.querySelector<HTMLElement>('#app')!
    cleanups.push(installElementPlusPopperContainer(appRoot))
    const trigger = document.querySelector<HTMLButtonElement>('#page-trigger')!
    trigger.focus()
    trigger.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))

    const container = document.createElement('div')
    container.id = 'el-popper-container-density'
    container.innerHTML = '<div class="el-popper"></div>'
    document.body.append(container)
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(container.querySelector<HTMLElement>('.el-popper')!.style.getPropertyValue(
      '--app-density-overlay-padding',
    )).toBe('24px')
    expect(container.querySelector<HTMLElement>('.el-popper')!.style.getPropertyValue(
      '--layout-table-cell-padding-y',
    )).toBe('14px')
  })

  it('页面触发且直接 Teleport 到 body 的 Dialog 同步页面密度', async () => {
    document.body.innerHTML = `
      <div id="app">
        <main class="v-page" style="--app-density-overlay-padding: 12px">
          <button id="dialog-trigger">open</button>
        </main>
      </div>
    `
    const appRoot = document.querySelector<HTMLElement>('#app')!
    cleanups.push(installElementPlusPopperContainer(appRoot))
    document.querySelector<HTMLButtonElement>('#dialog-trigger')!.dispatchEvent(
      new Event('pointerdown', { bubbles: true }),
    )

    const overlay = document.createElement('div')
    overlay.className = 'el-overlay'
    document.body.append(overlay)
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(overlay.style.getPropertyValue('--app-density-overlay-padding')).toBe('12px')
  })

  it('已打开浮层跟随其触发页密度更新，应用级浮层保持标准继承', async () => {
    document.body.innerHTML = '<div id="app"><main class="v-page" style="--app-density-overlay-padding:24px"><button>open</button></main></div>'
    const root = document.querySelector<HTMLElement>('#app')!
    cleanups.push(installElementPlusPopperContainer(root))
    const page = root.querySelector<HTMLElement>('.v-page')!
    page.querySelector('button')!.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    const overlay = document.createElement('div')
    overlay.className = 'el-overlay'
    document.body.append(overlay)
    await new Promise((resolve) => setTimeout(resolve, 0))
    page.style.setProperty('--app-density-overlay-padding', '12px')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(overlay.style.getPropertyValue('--app-density-overlay-padding')).toBe('12px')
    root.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    const appOverlay = document.createElement('div')
    appOverlay.className = 'el-overlay'
    root.append(appOverlay)
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(appOverlay.style.getPropertyValue('--app-density-overlay-padding')).toBe('')
  })
})
