import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse } from '@vue/compiler-sfc'
import { baseParse, type ElementNode, type RootNode, type TemplateChildNode } from '@vue/compiler-dom'
import { describe, expect, it } from 'vitest'

const srcRoot = fileURLToPath(new URL('../../', import.meta.url))
function vueFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const name = path.join(dir, entry.name)
    return entry.isDirectory() ? vueFiles(name) : name.endsWith('.vue') ? [name] : []
  })
}
function attribute(node: ElementNode, name: string) {
  return node.props.find(p => p.type === 6 && p.name === name)
}

describe('表单辅助说明复用契约', () => {
  it('字段说明经共享组件生成标记，禁止恢复私有说明样式', () => {
    const violations: string[] = []
    for (const file of vueFiles(srcRoot)) {
      const template = parse(fs.readFileSync(file, 'utf8')).descriptor.template
      if (!template) continue
      function walk(node: RootNode | TemplateChildNode, field = false) {
        if (node.type === 1) {
          // 选项描述、帮助浮层与设置字段已有独立渲染契约，不属于常显表单说明。
          if (['el-option', 'HelpHint', 'HelpTip', 'AppFormHelp'].includes(node.tag)) return
          const withinField = field || node.tag === 'el-form-item'
          const cls = attribute(node, 'class')
          const classes = cls?.type === 6 ? cls.value?.content.split(/\s+/) ?? [] : []
          const privateHelp = classes.some(c => [
            'app-caption-text', 'form-help', 'f-hint', 'stock-batch-hint', 'indicator-formula-help',
          ].includes(c))
          const privateSupplement = classes.some(c => ['cfg-hint', 'run-hint', 'cookie-note'].includes(c))
          // 下面是授权状态的事实时间、读取失败原因及只读事实值，不是输入说明。
          const fact = file.endsWith('ScheduleView.vue')
            && /cookieCredential\?\.(checked_at|saved_at|expires_at)|cookieStatus === 'unavailable'/.test(node.loc.source)
            || file.endsWith('TradeOperationEditor.vue') && node.loc.source.includes('conditionFactLabel(')
          if ((withinField && privateHelp || privateSupplement) && !fact) {
            violations.push(`${path.relative(srcRoot, file)}:${node.loc.start.line} ${node.tag}`)
          }
          for (const child of node.children) walk(child, withinField)
        } else if (node.type === 0) {
          for (const child of node.children) walk(child, field)
        }
      }
      walk(baseParse(template.content))
      // 调用方不能手动补标记；星号由组件统一管理，换行不改变标记数量。
      if (/<AppFormHelp\b[^>]*>\s*\*/.test(template.content)) {
        violations.push(`${path.relative(srcRoot, file)}: duplicated marker`)
      }
    }
    expect(violations).toEqual([])
  })
})
