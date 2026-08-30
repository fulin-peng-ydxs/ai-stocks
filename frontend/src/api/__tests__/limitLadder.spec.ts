// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_LIMIT_LADDER_FILTERS,
  exportLimitLadder,
  filtersFromRouteQuery,
  filtersToRouteQuery,
  toLimitLadderQueryParams,
} from '@/api/limitLadder'

vi.mock('@/api/authToken', () => ({ getAccessToken: () => 'test-token' }))

describe('limitLadder API filters', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('URL 状态经过规范化后可无损恢复', () => {
    const filters={...DEFAULT_LIMIT_LADDER_FILTERS,window:10 as const,boards:['main','gem'] as const,ignoreSt:false,oneWordOnly:true,keyword:'甲',hotspotType:'concept' as const,hotspotKey:'C001'}
    const query=filtersToRouteQuery({...filters,boards:[...filters.boards]})
    expect(filtersFromRouteQuery(query)).toEqual({...filters,boards:[...filters.boards]})
  })

  it('非法 URL 条件回退默认值且不保留残缺热点', () => {
    expect(filtersFromRouteQuery({
      window: '12',
      boards: 'unknown',
      hotspot_type: 'concept',
    })).toEqual(DEFAULT_LIMIT_LADDER_FILTERS)
  })

  it('URL 未显式声明的默认筛选沿用个人偏好', () => {
    const personal = {
      ...DEFAULT_LIMIT_LADDER_FILTERS,
      window: 20 as const,
      boards: ['star'] as const,
      ignoreSt: false,
    }
    expect(filtersFromRouteQuery({ keyword: ' 芯片 ' }, {
      ...personal,
      boards: [...personal.boards],
    })).toEqual({
      ...personal,
      boards: [...personal.boards],
      keyword: '芯片',
    })
  })

  it('CSV 与列表查询共享完全一致的规范化参数', async () => {
    const filters={...DEFAULT_LIMIT_LADDER_FILTERS,window:20 as const,boards:['star'] as const,ignoreSt:false,oneWordOnly:true,keyword:'科创',hotspotType:'industry' as const,hotspotKey:'I001'}
    const fetchMock=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('csv',{status:200,headers:{'content-disposition':'attachment; filename="limit.csv"'}}))
    const exported=await exportLimitLadder('2026-08-28',{...filters,boards:[...filters.boards]})
    const url=new URL(String(fetchMock.mock.calls[0][0]),'http://localhost')
    const expected=toLimitLadderQueryParams({...filters,boards:[...filters.boards]})
    expect(Object.fromEntries(url.searchParams.entries())).toEqual(Object.fromEntries(Object.entries(expected).filter(([,value])=>value!==undefined).map(([key,value])=>[key,String(value)])))
    expect(fetchMock.mock.calls[0][1]).toEqual({headers:{Authorization:'Bearer test-token'}})
    expect(exported.filename).toBe('limit.csv')
  })
})
