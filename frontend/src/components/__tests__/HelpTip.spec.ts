import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('../HelpTip.vue', import.meta.url), 'utf8')
const style = source.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1] ?? ''

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
})
