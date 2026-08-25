import { readdirSync, readFileSync } from 'node:fs'
import { extname, join } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('../HelpTip.vue', import.meta.url), 'utf8')
const style = source.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1] ?? ''
const itemSource = readFileSync(new URL('../HelpTipItem.vue', import.meta.url), 'utf8')
const itemStyle = itemSource.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1] ?? ''

function vueFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    return entry.isDirectory() ? vueFiles(path) : extname(path) === '.vue' ? [path] : []
  })
}

describe('HelpTip 主题样式契约', () => {
  it('提示图标和正文只消费预设语义 token，不维护私有 hex 色板', () => {
    expect(style).toContain('var(--el-fill-color-light)')
    expect(style).toContain('var(--el-border-color)')
    expect(style).toContain('var(--el-text-color-regular)')
    expect(style).toContain('var(--el-color-primary)')
    expect(style).toContain('var(--el-color-white)')
    expect(style).not.toMatch(/#[\da-f]{3,8}\b/i)
  })

  it('键盘聚焦与鼠标悬停共享主题主色反馈', () => {
    expect(source).toContain(`:trigger="['hover', 'focus']"`)
    expect(source).toContain('tabindex="0"')
    expect(source).toContain('role="button"')
    expect(style).toContain('.help-icon:focus-visible')
  })

  it('每项说明在具体问题与黄色注意项中二选一，内容统一使用点号列表', () => {
    expect(itemSource).toContain("warning ? '注意' : question")
    expect(itemSource).not.toContain('{{ topic }} /')
    expect(itemStyle).toContain('flex-direction: column')
    expect(itemStyle).toContain("content: '.'")
    expect(itemStyle).toContain('var(--app-warning-text)')
    expect(itemStyle).toContain('.help-tip-item.is-warning')
    expect(itemStyle).toContain('.help-tip-item + .help-tip-item')
    expect(itemStyle).not.toMatch(/#[\da-f]{3,8}\b/i)
  })

  it('所有 HelpTip 调用方只通过 HelpTipItem 声明独立说明项', () => {
    const srcDir = new URL('../../', import.meta.url).pathname
    const violations: string[] = []

    for (const file of vueFiles(srcDir)) {
      const componentSource = readFileSync(file, 'utf8')
      for (const match of componentSource.matchAll(/<HelpTip\b[^>]*>([\s\S]*?)<\/HelpTip>/g)) {
        const items = [...match[1].matchAll(/<HelpTipItem\b([^>]*)>([\s\S]*?)<\/HelpTipItem>/g)]
        const hasInvalidItem = items.some((item) => {
          const hasQuestion = /\bquestion=/.test(item[1])
          const hasWarning = /\bwarning\b/.test(item[1])
          const usesList = /^\s*<ul>[\s\S]*<\/ul>\s*$/.test(item[2])
          return hasQuestion === hasWarning || !usesList
        })
        const remainder = match[1]
          .replace(/<HelpTipItem\b[^>]*>[\s\S]*?<\/HelpTipItem>/g, '')
          .replace(/<!--[\s\S]*?-->/g, '')
          .trim()
        if (!items.length || hasInvalidItem || remainder) violations.push(file)
      }
    }

    expect(violations).toEqual([])
  })
})
