import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import postcss from 'postcss'
import { describe, expect, it } from 'vitest'
import { auditCloseControls, auditCloseControlsTree } from '../../../scripts/check-close-controls.mjs'

const audit = (source: string) => auditCloseControls([{ file: 'components/Fixture.vue', source }])
describe('关闭入口源码门禁', () => {
  it('生产代码共同消费关闭组件与唯一视觉配方', () => expect(auditCloseControlsTree()).toEqual([]))
  it('拒绝重新手写关闭图形及库样式', () => {
    expect(audit('<template><button><Close /></button></template>')).not.toEqual([])
    expect(audit('<style>.el-tag__close { color: red }</style>')).not.toEqual([])
  })
  it('拒绝缺少名称、私有尺寸和颜色，允许宿主管理布局与显隐', () => {
    expect(audit('<template><AppCloseButton /></template>')).not.toEqual([])
    expect(audit('<template><AppCloseButton label="关闭" class="close" /></template><style>.close { width: 18px; color: red }</style>')).toHaveLength(2)
    expect(audit('<template><AppCloseButton label="关闭" class="close" /></template><style>.close { flex: none; opacity: 0; margin-left: auto }</style>')).toEqual([])
    expect(audit('<template><AppCloseButton label="关闭" size="large" :style="privateStyle" /></template>')).toHaveLength(2)
  })
  it('共享配方覆盖库内置入口，并保留日期范围清空的隐藏机制', () => {
    const css = postcss.parse(readFileSync(resolve(__dirname, '../../styles/global.css'), 'utf8'))
    const adapters = ['.el-dialog__headerbtn', '.el-message-box__headerbtn', '.el-tag__close',
      '.el-input__clear', '.el-textarea__clear', '.el-select__clear', '.el-cascader__clear-btn',
      '.el-date-editor .clear-icon', '.el-date-editor .el-range__close-icon',
      '.el-alert__close-btn:not(.is-customed)', '.el-message__closeBtn', '.el-notification__closeBtn']
    const shared: string[] = []
    css.walkRules(rule => {
      if (!rule.selector.includes('.app-icon-button.app-close-control[data-close-size]')) return
      shared.push(rule.selector)
      expect(adapters.every(selector => rule.selector.includes(selector))).toBe(true)
      rule.walkDecls(decl => expect(['display', 'visibility', 'transform'].includes(decl.prop)).toBe(false))
    })
    expect(shared.length).toBeGreaterThan(1)
  })
  it('真实数据删除继续使用危险操作按钮', () => {
    expect(audit('<template><AppIconButton tone="danger" label="删除参数"><Close /></AppIconButton></template>')).toEqual([])
  })
})
