// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import ViolationReasonCombobox from '@/views/trade-discipline/components/ViolationReasonCombobox.vue'

const listReasons = vi.fn()
const deleteReason = vi.fn()
vi.mock('@/api/tradeDiscipline', () => ({
  listTradeDisciplineReasons: (...args: unknown[]) => listReasons(...args),
  deleteTradeDisciplineReason: (...args: unknown[]) => deleteReason(...args),
}))

describe('ViolationReasonCombobox', () => {
  beforeEach(() => {
    listReasons.mockResolvedValue([
      { code: 'impulsive', id: null, name: '冲动交易', builtin: true },
      { code: null, id: 'reason-1', name: '偏离观察期', builtin: false },
    ])
    deleteReason.mockResolvedValue({ reason_id: 'reason-1' })
  })
  afterEach(() => {
    document.body.innerHTML = ''
    vi.restoreAllMocks()
    vi.clearAllMocks()
  })

  it('自定义原因可行内删除，删除当前选择后立即清空；内置项无删除动作', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const wrapper = mount(ViolationReasonCombobox, {
      attachTo: document.body,
      props: {
        modelValue: { kind: 'custom', id: 'reason-1', name: '偏离观察期' },
      },
      global: { plugins: [ElementPlus], directives: { permission: {} } },
    })
    await flushPromises()
    await wrapper.get('.el-select__wrapper').trigger('click')
    await flushPromises()
    expect(document.body.querySelectorAll('.builtin-option-row')).toHaveLength(2)
    expect(document.body.querySelector('.builtin-option-label')?.textContent).toBe('内置')
    expect(document.body.querySelector('.builtin-option-row__action [aria-label="删除自定义原因"]'))
      .not.toBeNull()
    const buttons = Array.from(document.body.querySelectorAll('[aria-label="删除自定义原因"]'))
    expect(buttons).toHaveLength(1)
    expect(buttons[0].classList.contains('is-danger')).toBe(true)
    await new DOMWrapper(buttons[0] as Element).trigger('click')
    await flushPromises()
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      expect.any(String), '删除原因', expect.objectContaining({ confirmButtonType: 'danger' }),
    )
    expect(deleteReason).toHaveBeenCalledWith('reason-1')
    expect(wrapper.emitted('update:modelValue')).toContainEqual([null])
  })
})
