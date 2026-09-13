// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { installElementPlusPopperContainer } from '../elementPlusPopperContainer'

const cleanups: Array<() => void> = []

afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup())
  document.body.innerHTML = ''
})

describe('Element Plus Popper 缩放容器', () => {
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
})
