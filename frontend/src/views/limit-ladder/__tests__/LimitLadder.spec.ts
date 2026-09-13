// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { DEFAULT_LIMIT_LADDER_FILTERS, type LimitLadderResult, type LimitLadderStock } from '@/api/limitLadder'
import LadderHotspots from '@/views/limit-ladder/LadderHotspots.vue'
import LimitLadder from '@/views/limit-ladder/LimitLadder.vue'
import limitLadderSource from '@/views/limit-ladder/LimitLadder.vue?raw'
import LimitLadderCard from '@/views/limit-ladder/LimitLadderCard.vue'

const stock: LimitLadderStock = {
  code:'600001.SH',name:'甲软件',board:'主板',price_limit_pct:0.1,is_st:false,
  st_quality:'accurate',st_source:'daily_bar',is_one_word:true,consecutive_days:2,
  amount:123000000,industry_name:'软件',industry_board_code:'I001',source_version:'v1',
  window_limit_up_days:3,window_start_date:'2026-08-20',actual_trade_days:8,
  window_return_pct:12.34,
  snapshot_concepts:[{board_code:'C001',board_name:'人工智能'},{board_code:'C002',board_name:'机器人'}],
  latest_related_industry:{board_code:'I900',board_name:'数字服务',as_of_date:'2026-08-28'},
  latest_related_concept:{board_code:'C002',board_name:'机器人',as_of_date:'2026-08-28'},
}

const result: LimitLadderResult = {
  trade_date:'2026-08-28',business_code:'READY',snapshot_status:'valid',stored_snapshot_status:'valid',
  has_snapshot:true,filters:{},snapshot:{snapshot_id:'snapshot-1',trade_date:'2026-08-28',computed_at:'2026-08-28T18:00:00',stock_count:1,has_approx_st:false,coverage:{}},
  requested_window_start_date:'2026-07-17',requested_window_trade_days:31,dynamic_window_status:'ready',
  summary:{stock_count:1,highest_board:2,first_board_count:0},
  hotspots:{industry:[{group_key:'I900',group_name:'数字服务',stock_count:1}],concept:[{group_key:'C002',group_name:'机器人',stock_count:1}]},
  layers:[{consecutive_days:2,stock_count:1,stocks:[stock]}],
}

function router() {
  return createRouter({history:createMemoryHistory(),routes:[
    {path:'/',component:{template:'<div />'}},
    {path:'/sectors/:code',component:{template:'<div />'}},
  ]})
}

describe('LimitLadderCard', () => {
  it('展示精简卡片、走势相关行业和动态窗口统计', () => {
    const wrapper=mount(LimitLadderCard,{props:{stock,window:31,canViewSectors:true,returnPath:'/limit-ladder?restore=1'},global:{plugins:[ElementPlus,router()]}})
    expect(wrapper.text()).toContain('甲软件')
    expect(wrapper.text()).toContain('600001.SH')
    expect(wrapper.text()).toContain('31 日 3 板')
    expect(wrapper.text()).toContain('累计涨幅')
    expect(wrapper.text()).toContain('+12.34%')
    expect(wrapper.text()).toContain('窗口仅 8 日 · 自 2026-08-20 起')
    expect(wrapper.get('[data-testid="limit-ladder-related-industry"]').text()).toBe('数字服务')
    expect(wrapper.text()).not.toContain('软件 ·')
    expect(wrapper.text()).not.toContain('成交额')
    expect(wrapper.text()).not.toContain('截至')
    expect(wrapper.get('.limit-ladder-card__window-stat b').classes()).toContain('is-multiple')
    expect(wrapper.get('.limit-ladder-card__identity strong').attributes('title')).toBe('甲软件')
    expect(wrapper.get('[data-testid="limit-ladder-related-industry"]').attributes('title')).toBe('数字服务')
    expect(wrapper.get('[data-testid="limit-ladder-related-600001.SH"]').attributes('title')).toBe('机器人')
    expect(wrapper.get('[data-testid="limit-ladder-related-600001.SH"]').attributes('href')).toBe('/sectors/C002?return_to=/limit-ladder?restore=1')
  })

  it('X 日 N 板仅在 N 大于 1 时强调数字', () => {
    const wrapper=mount(LimitLadderCard,{props:{stock:{...stock,consecutive_days:1,window_limit_up_days:1},window:31,canViewSectors:false},global:{plugins:[ElementPlus,router()]}})
    expect(wrapper.get('.limit-ladder-card__window-stat').text()).toContain('31 日 1 板')
    expect(wrapper.get('.limit-ladder-card__window-stat b').classes()).not.toContain('is-multiple')
  })

  it('无走势冠军时统一显示破折号，有原因时支持聚焦查看', () => {
    const emptyStock: LimitLadderStock = {
      ...stock,
      latest_related_industry: null,
      latest_related_concept: null,
      latest_related_industry_empty_reason: {
        code: 'insufficient_samples',
        message: '共同有效样本不足：20 日最高 14/15，60 日最高 54/40',
        max_sample_20: 14,
        required_sample_20: 15,
        max_sample_60: 54,
        required_sample_60: 40,
      },
      latest_related_concept_empty_reason: null,
    }
    const wrapper=mount(LimitLadderCard,{props:{stock:emptyStock,window:31,canViewSectors:false},global:{plugins:[ElementPlus,router()]}})

    expect(wrapper.get('[data-testid="limit-ladder-related-industry"]').text()).toBe('—')
    expect(wrapper.get('.related-board-empty-value--explained').attributes('tabindex')).toBe('0')
    expect(wrapper.get('.related-board-empty-value--explained').attributes('aria-label'))
      .toContain('暂无行业走势，原因：共同有效样本不足')
    expect(wrapper.find('.limit-ladder-card__empty').exists()).toBe(false)
    expect(wrapper.findAll('.related-board-empty-value').map((item) => item.text())).toEqual(['—', '—'])
  })

  it('概念点击只跳板块，不触发卡片选择；无权限时退化只读', async () => {
    const wrapper=mount(LimitLadderCard,{props:{stock,window:31,canViewSectors:true},global:{plugins:[ElementPlus,router()]}})
    await wrapper.get('[data-testid="limit-ladder-related-600001.SH"]').trigger('click')
    expect(wrapper.emitted('select')).toBeUndefined()
    await wrapper.setProps({canViewSectors:false})
    expect(wrapper.find('[data-testid="limit-ladder-related-600001.SH"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('机器人')
    expect(wrapper.get('.limit-ladder-card__concept > span').attributes('tabindex')).toBeUndefined()
  })

  it('使用明确按钮选择股票，板块链接不嵌套在按钮内', async () => {
    const wrapper=mount(LimitLadderCard,{props:{stock,window:31,canViewSectors:true},global:{plugins:[ElementPlus,router()]}})
    const card=wrapper.get('article')
    const select=wrapper.get('[data-testid="limit-ladder-card-select-600001.SH"]')
    const related=wrapper.get('[data-testid="limit-ladder-related-600001.SH"]')
    expect(card.attributes('tabindex')).toBeUndefined()
    expect(select.element.tagName).toBe('BUTTON')
    expect(select.attributes('aria-label')).toBe('选择甲软件查看走势')
    expect(select.element.contains(related.element)).toBe(false)
    await select.trigger('click')
    expect(wrapper.emitted('select')).toEqual([[stock]])
  })

  it('选中态同时提供边框和 aria-current，不只依赖颜色', () => {
    const wrapper=mount(LimitLadderCard,{props:{stock,window:31,canViewSectors:true,selected:true},global:{plugins:[ElementPlus,router()]}})
    expect(wrapper.classes()).toContain('limit-ladder-card--selected')
    expect(wrapper.attributes('aria-current')).toBe('true')
    expect(wrapper.get('.limit-ladder-card__select').attributes('aria-current')).toBe('true')
    expect(wrapper.attributes('data-stock-code')).toBe(stock.code)
  })
})

describe('LimitLadder layout', () => {
  it('结果区与内容体共同成长，使大尺寸状态块按完整可用区域居中', () => {
    const contentRule = limitLadderSource.match(/\.limit-ladder__content \{([^}]*)\}/)?.[1] ?? ''
    const bodyRule = limitLadderSource.match(/\.limit-ladder__body \{([^}]*)\}/)?.[1] ?? ''

    expect(contentRule).toContain('display: flex')
    expect(contentRule).toContain('flex-direction: column')
    expect(bodyRule).toContain('flex: 1 0 auto')
    expect(bodyRule).toContain('flex-direction: column')
    expect(bodyRule).toContain('width: 100%')
  })
})

describe('LadderHotspots', () => {
  it('按每股唯一的走势最相关概念输出热点交集条件', async () => {
    const wrapper=mount(LadderHotspots,{props:{hotspots:result.hotspots,activeType:'industry',activeKey:'I001'}})
    const concept = wrapper.get('[data-testid="limit-ladder-hotspot-concept-C002"]')
    expect(concept.get('.ladder-hotspots__separator').text()).toBe('·')
    expect(concept.get('b').text()).toBe('1只')
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

  it('低高度双栏按紧凑上限收敛热点，并保留当前筛选项', () => {
    const concepts=Array.from({length:8},(_,index)=>({group_key:`C${index}`,group_name:`概念${index}`,stock_count:8-index}))
    const wrapper=mount(LadderHotspots,{props:{hotspots:{industry:[],concept:concepts},activeType:'concept',activeKey:'C7',compact:true}})
    expect(wrapper.findAll('.ladder-hotspots__chip')).toHaveLength(4)
    expect(wrapper.text()).toContain('概念7')
    expect(wrapper.get('.ladder-hotspots__more').text()).toContain('展开其余 4 项')
  })
})

describe('LimitLadder', () => {
  it('摘要、层级与热点使用同一服务端结果并联动筛选', async () => {
    const wrapper=mount(LimitLadder,{props:{result,filters:{...DEFAULT_LIMIT_LADDER_FILTERS},tradeDate:'2026-08-28',loading:false,error:'',canViewSectors:true},global:{plugins:[ElementPlus,router()],stubs:{TradeDatePicker:true}}})
    expect(wrapper.get('[data-testid="limit-ladder-summary-total"]').text()).toBe('1')
    expect(wrapper.get('[data-testid="limit-ladder-summary-total"]').classes()).toContain('is-total')
    expect(wrapper.find('.limit-ladder__summary .is-highest').exists()).toBe(true)
    expect(wrapper.find('.limit-ladder__summary .is-first').exists()).toBe(true)
    expect(wrapper.get('[data-testid="limit-ladder-layer-2"]').text()).toContain('2 连板')
    await wrapper.get('[data-testid="limit-ladder-hotspot-concept-C002"]').trigger('click')
    expect(wrapper.emitted('update:filters')).toContainEqual([{
      ...DEFAULT_LIMIT_LADDER_FILTERS,hotspotType:'concept',hotspotKey:'C002',
    }])
  })

  it('重置筛选按钮无图标并恢复全部默认筛选', async () => {
    const wrapper=mount(LimitLadder,{props:{result,filters:{...DEFAULT_LIMIT_LADDER_FILTERS,keyword:'甲',oneWordOnly:true},tradeDate:'2026-08-28',loading:false,error:'',canViewSectors:true},global:{plugins:[ElementPlus,router()],stubs:{TradeDatePicker:true}}})
    const reset=wrapper.get('[data-testid="limit-ladder-reset"]')
    expect(reset.text()).toBe('重置筛选')
    expect(reset.find('.el-icon').exists()).toBe(false)
    await reset.trigger('click')
    expect(wrapper.emitted('update:filters')).toContainEqual([{
      ...DEFAULT_LIMIT_LADDER_FILTERS,
    }])
  })

  it('筛选条件为默认值时禁用重置筛选', () => {
    const wrapper=mount(LimitLadder,{props:{result,filters:{...DEFAULT_LIMIT_LADDER_FILTERS},tradeDate:'2026-08-28',loading:false,error:'',canViewSectors:true},global:{plugins:[ElementPlus,router()],stubs:{TradeDatePicker:true}}})
    expect(wrapper.get('[data-testid="limit-ladder-reset"]').attributes('disabled')).toBeDefined()
  })

  it('所有梯级使用同一宽度，不再按板位缩窄', () => {
    const firstBoardStock={...stock,code:'000001.SZ',name:'乙银行',consecutive_days:1,window_limit_up_days:1}
    const wrapper=mount(LimitLadder,{props:{result:{...result,layers:[...result.layers,{consecutive_days:1,stock_count:1,stocks:[firstBoardStock]}]},filters:{...DEFAULT_LIMIT_LADDER_FILTERS},tradeDate:'2026-08-28',loading:false,error:'',canViewSectors:true},global:{plugins:[ElementPlus,router()],stubs:{TradeDatePicker:true}}})
    expect(wrapper.get('[data-testid="limit-ladder-layer-2"]').attributes('style')).toBeUndefined()
    expect(wrapper.get('[data-testid="limit-ladder-layer-1"]').attributes('style')).toBeUndefined()
  })

  it('筛选空与合法空快照使用不同提示', async () => {
    const wrapper=mount(LimitLadder,{props:{result:{...result,business_code:'FILTER_EMPTY',summary:{stock_count:0,highest_board:null,first_board_count:0},layers:[]},filters:{...DEFAULT_LIMIT_LADDER_FILTERS},tradeDate:'2026-08-28',loading:false,error:'',canViewSectors:false},global:{plugins:[ElementPlus],stubs:{TradeDatePicker:true}}})
    expect(wrapper.text()).toContain('当前筛选无匹配股票')
    await wrapper.setProps({result:{...result,business_code:'EMPTY_SNAPSHOT',summary:{stock_count:0,highest_board:null,first_board_count:0},layers:[]}})
    expect(wrapper.text()).toContain('当日无涨停股票')
  })

  it('区分计算中、非交易日、覆盖失败和带旧结果的过期状态', async () => {
    const wrapper=mount(LimitLadder,{props:{result:{...result,has_snapshot:false,business_code:'SNAPSHOT_PENDING',snapshot_status:'calculating',snapshot:null,layers:[]},filters:{...DEFAULT_LIMIT_LADDER_FILTERS},tradeDate:'2026-08-28',loading:false,error:'',canViewSectors:false},global:{plugins:[ElementPlus],stubs:{TradeDatePicker:true}}})
    expect(wrapper.text()).toContain('天梯快照正在计算')
    expect(wrapper.get('[data-testid="limit-ladder-state"]').classes())
      .toContain('app-state-block--loading')
    expect(wrapper.text()).toContain('页面最多等待 2 分钟')
    expect(wrapper.find('[data-testid="limit-ladder-summary-total"]').exists()).toBe(false)

    await wrapper.setProps({result:{...result,has_snapshot:false,business_code:'NOT_TRADING_DAY',snapshot_status:'not_trading_day',snapshot:null,layers:[],nearest_previous_trade_date:'2026-08-27'}})
    expect(wrapper.text()).toContain('所选日期不是交易日')
    expect(wrapper.text()).toContain('最近交易日为 2026-08-27')
    expect(wrapper.findAll('button').some((button) => button.text() === '重试')).toBe(false)

    await wrapper.setProps({result:{...result,has_snapshot:false,business_code:'SNAPSHOT_FAILED',snapshot_status:'failed',snapshot:null,layers:[],failure_summary:'MISSING_BAR_OR_SUSPENSION'}})
    expect(wrapper.text()).toContain('天梯快照计算失败')
    expect(wrapper.text()).toContain('部分股票缺少行情或停牌确认')
    expect(wrapper.text()).toContain('刷新状态')

    await wrapper.setProps({ canManageData: true, canRecompute: true })
    expect(wrapper.text()).toContain('重新计算')
    await wrapper.get('button.el-button--primary').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)

    await wrapper.setProps({canManageData:false,result:{...result,has_snapshot:false,business_code:'SNAPSHOT_NOT_READY',snapshot_status:'invalid',snapshot:null,layers:[],invalid_reason:'INGEST_PARTIAL',coverage:{reason_codes:['INGEST_PARTIAL']}}})
    expect(wrapper.text()).toContain('当日行情采集未完整成功')
    expect(wrapper.text()).toContain('请联系有数据任务权限的管理员执行行情补采')
    expect(wrapper.text()).not.toContain('去补采行情')

    await wrapper.setProps({ canManageData: true, canRecompute: true })
    expect(wrapper.text()).toContain('请前往“数据采集”执行“日常同步”')
    expect(wrapper.text()).toContain('返回本页点击“重算当日”')
    await wrapper.get('button.el-button--primary.is-plain').trigger('click')
    expect(wrapper.emitted('openIngest')).toHaveLength(1)

    await wrapper.setProps({result:{...result,business_code:'SNAPSHOT_STALE',snapshot_status:'recalculating',last_success_at:'2026-08-28T18:00:00'}})
    expect(wrapper.get('[data-testid="limit-ladder-stale-notice"]').text()).toContain('结果已过期')
    expect(wrapper.get('[data-testid="limit-ladder-stale-notice"]').text()).toContain('当前版本正在重算')
    expect(wrapper.get('[data-testid="limit-ladder-stale-notice"]').text()).toContain('当前展示 2026-08-28T18:00:00 生成的最后成功版本')
    expect(wrapper.get('[data-testid="limit-ladder-stale-notice"]').text()).toContain('计算完成后将自动刷新')
    expect(wrapper.get('[data-testid="limit-ladder-layer-2"]').text()).toContain('2 连板')

    await wrapper.setProps({result:{
      ...result,
      business_code:'ST_STATUS_NOT_READY',
      snapshot_status:'st_status_not_ready',
      st_status_error:'ST 点时事实批次状态为 refreshing',
    }})
    const stNotice=wrapper.get('[data-testid="limit-ladder-stale-notice"]')
    expect(stNotice.text()).toContain('ST 状态尚未就绪')
    expect(stNotice.text()).toContain('未把旧快照判定为有效结果')
    expect(stNotice.text()).toContain('最后成功版本供核对')
    expect(wrapper.get('[data-testid="limit-ladder-layer-2"]').text()).toContain('2 连板')
  })

  it('主动加载和失败状态接管结果区，不与旧摘要热点并存', async () => {
    const wrapper=mount(LimitLadder,{props:{result,filters:{...DEFAULT_LIMIT_LADDER_FILTERS},tradeDate:'2026-08-28',loading:true,error:'',canViewSectors:false},global:{plugins:[ElementPlus],stubs:{TradeDatePicker:true}}})
    expect(wrapper.find('[data-testid="limit-ladder-summary-total"]').exists()).toBe(false)
    expect(wrapper.find('.ladder-hotspots').exists()).toBe(false)
    expect(wrapper.text()).toContain('正在加载天梯快照')
    await wrapper.setProps({loading:false,error:'网络失败'})
    expect(wrapper.find('[data-testid="limit-ladder-summary-total"]').exists()).toBe(false)
    expect(wrapper.find('.ladder-hotspots').exists()).toBe(false)
    expect(wrapper.text()).toContain('网络失败')
  })

  it('403 使用无权限状态且不提供重试操作', () => {
    const wrapper=mount(LimitLadder,{props:{result:null,filters:{...DEFAULT_LIMIT_LADDER_FILTERS},tradeDate:'2026-08-28',loading:false,error:'',forbidden:true,canViewSectors:false},global:{plugins:[ElementPlus],stubs:{TradeDatePicker:true}}})
    const state=wrapper.get('[data-testid="limit-ladder-state"]')
    expect(state.classes()).toContain('app-state-block--permission')
    expect(state.text()).toContain('无权限查看连板天梯')
    expect(state.text()).toContain('请联系系统管理员调整权限')
    expect(state.findAll('button').some((button) => button.text() === '重试')).toBe(false)
  })
})
