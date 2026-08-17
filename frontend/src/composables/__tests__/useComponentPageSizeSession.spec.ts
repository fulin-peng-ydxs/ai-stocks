import { nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { MAX_PAGE_SIZE } from '@/constants/pagination'
import { useComponentPageSizeSession } from '../useComponentPageSizeSession'

describe('useComponentPageSizeSession', () => {
  it('统一规范默认值，并在默认变化时归页重载', async () => {
    const configured = ref<unknown>(50)
    const resetPage = vi.fn()
    const reload = vi.fn()
    const { pageSize } = useComponentPageSizeSession({
      resolveDefault: () => configured.value,
      resetPage,
      reload,
    })

    expect(pageSize.value).toBe(50)
    configured.value = 500
    await nextTick()

    expect(pageSize.value).toBe(MAX_PAGE_SIZE)
    expect(resetPage).toHaveBeenCalledTimes(1)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('页面切换每页条数只改会话值，并统一归页重载', () => {
    const configured = ref(20)
    const resetPage = vi.fn()
    const reload = vi.fn()
    const { pageSize, changePageSize } = useComponentPageSizeSession({
      resolveDefault: () => configured.value,
      resetPage,
      reload,
    })

    changePageSize(100)

    expect(pageSize.value).toBe(100)
    expect(configured.value).toBe(20)
    expect(resetPage).toHaveBeenCalledTimes(1)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('会话恢复期间拒绝迟到默认值覆盖和重载', async () => {
    const configured = ref(20)
    const restoring = ref(true)
    const resetPage = vi.fn()
    const reload = vi.fn()
    const { pageSize } = useComponentPageSizeSession({
      resolveDefault: () => configured.value,
      shouldSync: () => !restoring.value,
      resetPage,
      reload,
    })

    pageSize.value = 100
    configured.value = 50
    await nextTick()

    expect(pageSize.value).toBe(100)
    expect(resetPage).not.toHaveBeenCalled()
    expect(reload).not.toHaveBeenCalled()
  })

  it('允许页面保留专属分页候选归一化规则', () => {
    const configured = ref<unknown>(30)
    const normalize = (value: unknown) => [10, 20, 30, 50].includes(Number(value))
      ? Number(value)
      : 20
    const { pageSize, changePageSize } = useComponentPageSizeSession({
      resolveDefault: () => configured.value,
      normalize,
      resetPage: vi.fn(),
      reload: vi.fn(),
    })

    expect(pageSize.value).toBe(30)
    changePageSize(200)
    expect(pageSize.value).toBe(20)
  })
})
