// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { DEFAULT_LIMIT_LADDER_FILTERS, type LimitLadderResult, type LimitLadderStock } from '@/api/limitLadder'
import LadderHotspots from '@/views/limit-ladder/LadderHotspots.vue'
import LimitLadder from '@/views/limit-ladder/LimitLadder.vue'
import LimitLadderCard from '@/views/limit-ladder/LimitLadderCard.vue'

const stock: LimitLadderStock = {
  code:'600001.SH',name:'甲软件',board:'主板',price_limit_pct:0.1,is_st:false,
  st_quality:'accurate',st_source:'daily_bar',is_one_word:true,consecutive_days:2,
  amount:123000000,industry_name:'软件',industry_board_code:'I001',source_version:'v1',
  window_limit_up_days:3,window_start_date:'2026-08-20',actual_trade_days:8,
  snapshot_concepts:[{board_code:'C001',board_name:'人工智能'},{board_code:'C002',board_name:'机器人'}],
  latest_related_concept:{board_code:'C002',board_name:'机器人',as_of_date:'2026-08-28'},
}

const result: LimitLadderResult = {
  trade_date:'2026-08-28',business_code:'READY',snapshot_status:'valid',stored_snapshot_status:'valid',
  has_snapshot:true,filters:{},snapshot:{snapshot_id:'snapshot-1',trade_date:'2026-08-28',computed_at:'2026-08-28T18:00:00',stock_count:1,has_approx_st:false,coverage:{}},
  requested_window_start_date:'2026-07-17',requested_window_trade_days:31,dynamic_window_status:'ready',
  summary:{stock_count:1,highest_board:2,first_board_count:0},
  hotspots:{industry:[{group_key:'I001',group_name:'软件',stock_count:1}],concept:[{group_key:'C002',group_name:'机器人',stock_count:1}]},
  layers:[{consecutive_days:2,stock_count:1,stocks:[stock]}],
}

function router() {
  return createRouter({history:createMemoryHistory(),routes:[
    {path:'/',component:{template:'<div />'}},
    {path:'/sectors/:code',component:{template:'<div />'}},
  ]})
}

describe('LimitLadderCard', () => {
  it('展示完整板位字段与短上市实际起始日', () => {
    const wrapper=mount(LimitLadderCard,{props:{stock,window:31,canViewSectors:true},global:{plugins:[ElementPlus,router()]}})
    expect(wrapper.text()).toContain('甲软件')
    expect(wrapper.text()).toContain('2 连板')
    expect(wrapper.text()).toContain('31 日 3 板')
    expect(wrapper.text()).toContain('窗口仅 8 日 · 自 2026-08-20 起')
    expect(wrapper.text()).toContain('成交额 1.23 亿')
    expect(wrapper.get('[data-testid="limit-ladder-related-600001.SH"]').attributes('href')).toBe('/sectors/C002')
  })

  it('概念点击只跳板块，不触发卡片选择；无权限时退化只读', async () => {
    const wrapper=mount(LimitLadderCard,{props:{stock,window:31,canViewSectors:true},global:{plugins:[ElementPlus,router()]}})
    await wrapper.get('[data-testid="limit-ladder-related-600001.SH"]').trigger('click')
    expect(wrapper.emitted('select')).toBeUndefined()
    await wrapper.setProps({canViewSectors:false})
    expect(wrapper.find('[data-testid="limit-ladder-related-600001.SH"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('机器人')
  })

  it('选中态同时提供边框和 aria-current，不只依赖颜色', () => {
    const wrapper=mount(LimitLadderCard,{props:{stock,window:31,canViewSectors:true,selected:true},global:{plugins:[ElementPlus,router()]}})
    expect(wrapper.classes()).toContain('limit-ladder-card--selected')
    expect(wrapper.attributes('aria-current')).toBe('true')
    expect(wrapper.attributes('data-stock-code')).toBe(stock.code)
  })
})

describe('LadderHotspots', () => {
  it('按每股唯一的走势最相关概念输出热点交集条件', async () => {
    const wrapper=mount(LadderHotspots,{props:{hotspots:result.hotspots,activeType:'industry',activeKey:'I001'}})
    expect(wrapper.text()).toContain('机器人1')
    await wrapper.get('[data-testid="limit-ladder-hotspot-concept-C002"]').trigger('click')
    expect(wrapper.emitted('toggle')).toEqual([['concept','C002']])
  })

  it('大量热点默认收敛并允许展开，避免挤压天梯主体', async () => {
    const concepts=Array.from({length:15},(_,index)=>({group_key:`C${index}`,group_name:`概念${index}`,stock_count:15-index}))
    const wrapper=mount(LadderHotspots,{props:{hotspots:{industry:[],concept:concepts},activeType:'concept',activeKey:'C14'}})
    expect(wrapper.findAll('.ladder-hotspots__chip')).toHaveLength(12)
    expect(wrapper.text()).toContain('概念14')
    await wrapper.get('.ladder-hotspots__more').trigger('click')
    expect(wrapper.findAll('.ladder-hotspots__chip')).toHaveLength(15)
    expect(wrapper.text()).toContain('收起')
  })
})

describe('LimitLadder', () => {
  it('摘要、层级与热点使用同一服务端结果并联动筛选', async () => {
    const wrapper=mount(LimitLadder,{props:{result,filters:{...DEFAULT_LIMIT_LADDER_FILTERS},tradeDate:'2026-08-28',loading:false,error:'',exporting:false,canViewSectors:true},global:{plugins:[ElementPlus,router()],stubs:{TradeDatePicker:true}}})
    expect(wrapper.get('[data-testid="limit-ladder-summary-total"]').text()).toBe('1')
    expect(wrapper.get('[data-testid="limit-ladder-layer-2"]').text()).toContain('2 连板')
    await wrapper.get('[data-testid="limit-ladder-hotspot-concept-C002"]').trigger('click')
    expect(wrapper.emitted('update:filters')).toContainEqual([{
      ...DEFAULT_LIMIT_LADDER_FILTERS,hotspotType:'concept',hotspotKey:'C002',
    }])
  })

  it('筛选空与合法空快照使用不同提示', async () => {
    const wrapper=mount(LimitLadder,{props:{result:{...result,business_code:'FILTER_EMPTY',summary:{stock_count:0,highest_board:null,first_board_count:0},layers:[]},filters:{...DEFAULT_LIMIT_LADDER_FILTERS},tradeDate:'2026-08-28',loading:false,error:'',exporting:false,canViewSectors:false},global:{plugins:[ElementPlus],stubs:{TradeDatePicker:true}}})
    expect(wrapper.text()).toContain('当前筛选无匹配股票')
    await wrapper.setProps({result:{...result,business_code:'EMPTY_SNAPSHOT',summary:{stock_count:0,highest_board:null,first_board_count:0},layers:[]}})
    expect(wrapper.text()).toContain('当日无涨停股票')
  })

  it('区分计算中、非交易日、覆盖失败和带旧结果的过期状态', async () => {
    const wrapper=mount(LimitLadder,{props:{result:{...result,has_snapshot:false,business_code:'SNAPSHOT_PENDING',snapshot_status:'calculating',snapshot:null,layers:[]},filters:{...DEFAULT_LIMIT_LADDER_FILTERS},tradeDate:'2026-08-28',loading:false,error:'',exporting:false,canViewSectors:false},global:{plugins:[ElementPlus],stubs:{TradeDatePicker:true}}})
    expect(wrapper.text()).toContain('天梯快照正在计算')
    expect(wrapper.find('[data-testid="limit-ladder-summary-total"]').exists()).toBe(false)

    await wrapper.setProps({result:{...result,has_snapshot:false,business_code:'NOT_TRADING_DAY',snapshot_status:'not_trading_day',snapshot:null,layers:[],nearest_previous_trade_date:'2026-08-27'}})
    expect(wrapper.text()).toContain('所选日期不是交易日')
    expect(wrapper.text()).toContain('最近交易日为 2026-08-27')
    expect(wrapper.findAll('button').some((button) => button.text() === '重试')).toBe(false)

    await wrapper.setProps({result:{...result,has_snapshot:false,business_code:'SNAPSHOT_FAILED',snapshot_status:'failed',snapshot:null,layers:[],failure_summary:'MISSING_BAR_OR_SUSPENSION'}})
    expect(wrapper.text()).toContain('天梯快照计算失败')
    expect(wrapper.text()).toContain('部分股票缺少行情或停牌确认')
    expect(wrapper.text()).toContain('重试')

    await wrapper.setProps({result:{...result,business_code:'SNAPSHOT_STALE',snapshot_status:'recalculating',last_success_at:'2026-08-28T18:00:00'}})
    expect(wrapper.get('[data-testid="limit-ladder-stale-notice"]').text()).toContain('结果已过期')
    expect(wrapper.get('[data-testid="limit-ladder-stale-notice"]').text()).toContain('当前展示最后成功版本')
    expect(wrapper.get('[data-testid="limit-ladder-layer-2"]').text()).toContain('2 连板')
  })
})
