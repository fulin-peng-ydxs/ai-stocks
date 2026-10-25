import { describe, expect, it } from 'vitest'
import { auditTooltipContract, auditTooltipTree } from '../../../scripts/check-tooltip-contract.mjs'

const audit = (source: string) => auditTooltipContract([{ file: 'components/Fixture.vue', source }])
describe('可访问名称与提示入口契约', () => {
  it('生产代码不恢复原生提示和旧自动接口', () => expect(auditTooltipTree()).toEqual([]))
  it('拒绝原生及透传到控件的 title，拒绝旧接口', () => {
    expect(audit('<template><button title="关闭"/><el-select :title="hint"/><AppIconButton label="设置" :native-title="false"/></template>')).toHaveLength(3)
    expect(audit('<script setup>const nativeTitle = true</script>')).not.toEqual([])
    expect(audit('<template><AppCloseButton label="关闭" tooltip="关闭" /></template>')).not.toEqual([])
  })
  it('组件标题、插槽名和 iframe 名称不误报，显式提示与原文字段有效', () => {
    expect(audit('<template><AppDialog title="详情"/><el-alert title="失败"/><el-popover title="说明"/><iframe title="预览"/><template #title>标题</template><AppIconButton label="设置" tooltip="页面设置"/><span :data-overflow-tooltip-content="fullText">摘要</span></template>')).toEqual([])
  })
  it('图标按钮的默认提示依赖非空名称，允许默认提示及显式豁免', () => {
    expect(audit('<template>\n<AppIconButton/>\n<AppIconButton label=" "/>\n<AppIconButton :label=""/>\n</template>')).toHaveLength(3)
    expect(audit('<template><AppIconButton label="刷新"/><AppIconButton :label="actionLabel"/><AppIconButton label="关闭" :tooltip="false"/></template>')).toEqual([])
  })
  it('外层提示必须复用单一入口，避免默认提示生成双气泡', () => {
    expect(audit('<template>\n<AppHoverInfo content="说明"><AppIconButton label="操作"/></AppHoverInfo>\n<AppActionHint text="原因"><AppIconButton label="删除"/></AppActionHint>\n</template>')).toHaveLength(2)
    expect(audit('<template><AppHoverInfo content="说明"><AppIconButton label="操作" :tooltip="false"/></AppHoverInfo></template>')).toEqual([])
  })
  it('渲染函数与运行时属性写入不能绕过门禁，业务标题对象允许保留', () => {
    expect(audit('<script setup>h("button", { title: hint }); element.setAttribute("title", hint)</script>')).toHaveLength(2)
    expect(audit('<script setup>const route = {meta: { title: "榜单" }}</script>')).toEqual([])
  })
})
