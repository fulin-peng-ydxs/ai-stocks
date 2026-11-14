// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { h, nextTick } from 'vue'
import { ElConfigProvider, ElMessage } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { APP_MESSAGE_POLICY } from '../messagePolicy'

afterEach(() => {
  ElMessage.closeAll()
  vi.useRealTimers()
})

describe('全局消息展示策略', () => {
  it('不同来源和级别的消息统一自动消失，无须手动关闭', async () => {
    vi.useFakeTimers()
    const provider = mount(ElConfigProvider, {
      props: { message: APP_MESSAGE_POLICY }, slots: { default: () => h('div') },
    })
    // 对应页面成功、修复失败、业务警告和请求层错误，共用真实库的全局入口。
    ElMessage.success('保存成功')
    ElMessage({ type: 'error', message: '目标日数据尚未补齐' })
    ElMessage.warning('来源仍待更新')
    ElMessage.error('请求超时，请稍后重试')
    await nextTick()
    expect(document.querySelectorAll('.el-message')).toHaveLength(4)
    expect(document.querySelector('.el-message__closeBtn')).toBeNull()
    await vi.advanceTimersByTimeAsync(2900)
    expect(document.querySelectorAll('.el-message')).toHaveLength(4)
    await vi.advanceTimersByTimeAsync(500)
    expect(document.querySelectorAll('.el-message')).toHaveLength(0)
    provider.unmount()
  })
})
