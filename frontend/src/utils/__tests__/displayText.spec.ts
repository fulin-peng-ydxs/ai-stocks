import { describe, expect, it } from 'vitest'
import { businessMessage, enumText } from '../displayText'
import { getErrorMessage } from '../error'

describe('业务文案与技术诊断边界', () => {
  it('未知枚举不回显原码，原始定位值不受转换影响', () => {
    const value = 'new_internal_type'
    expect(enumText({ done: '已完成' }, value, '未识别任务类型')).toBe('未识别任务类型')
    expect(value).toBe('new_internal_type')
    expect(enumText({ done: '已完成' }, 'done')).toBe('已完成')
    expect(enumText({}, null)).toBe('—')
    expect(enumText({}, 'constructor')).toBe('未识别')
    expect(enumText({}, 'toString')).toBe('未识别')
  })
  it.each([
    'SQL 执行失败: Binder Error\nSQL: SELECT secret FROM private_table',
    'HTTPError: 502 for url: https://example.test/private',
    '查询失败: SELECT code FROM stock_basic', 'Traceback: 系统异常',
    '{"intraday_gap":1}', '[object Object]', 'Network Error', undefined, { count: 0 },
  ])('普通反馈不输出技术原文：%s', value => {
    expect(businessMessage(value, '操作失败，请查看任务日志')).toBe('操作失败，请查看任务日志')
  })
  it('保留可读业务原因、专业标识与真实零值', () => {
    expect(businessMessage('MACD 历史不足，缺失 0 项', '失败')).toBe('MACD 历史不足，缺失 0 项')
    expect(businessMessage('参数范围无效，请检查开始日期', '失败')).toContain('开始日期')
  })
  it('解析错误用导入提示，远程错误优先使用已转换的中文反馈', () => {
    expect(getErrorMessage(new SyntaxError('Unexpected token'), '配置文件格式不正确')).toBe('配置文件格式不正确')
    expect(getErrorMessage({ uiMessage: '当前无权保存', message: 'Request failed with status code 403' }))
      .toBe('当前无权保存')
    expect(getErrorMessage({ response: { status: 200, data: { msg: 'SQL: SELECT x' } } }, '读取失败'))
      .toBe('读取失败')
  })
})
