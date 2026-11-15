// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import HelpHint from '@/components/HelpHint.vue'
import StockChartPanelHeader from '../StockChartPanelHeader.vue'

describe('图表标题与口径说明', () => {
  it('动态复权及 MACD 参数进入共享帮助入口，切换时更新并保留可访问名称', async () => {
    const wrapper = mount(StockChartPanelHeader, { props: {title:'K线（前复权）'}, global: {stubs:{AppHoverInfo:{template:'<span><slot /></span>'}}} })
    try {
      expect(wrapper.get('.stock-chart-panel__title').text()).toBe('K线')
      expect(wrapper.getComponent(HelpHint).props()).toMatchObject({text:'前复权',label:'K线口径说明'})
      expect(wrapper.get('.help-hint').attributes()).toMatchObject({tabindex:'0',role:'button','aria-label':'K线口径说明'})
      await wrapper.setProps({title:'MACD（12,26,9·后复权）'})
      expect(wrapper.get('.stock-chart-panel__title').text()).toBe('MACD')
      expect(wrapper.getComponent(HelpHint).props('text')).toBe('12,26,9·后复权')
      await wrapper.setProps({title:'量能'})
      expect(wrapper.findComponent(HelpHint).exists()).toBe(false)
    } finally { wrapper.unmount() }
  })
})
