import { nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useDefaultedSessionValue } from '../useDefaultedSessionValue'

describe('useDefaultedSessionValue', () => {
  it('默认值单向同步到会话值，会话修改不反写默认值', async () => {
    const defaultValue = ref(20)
    const onSynced = vi.fn()
    const sessionValue = useDefaultedSessionValue(defaultValue, { onSynced })

    sessionValue.value = 50
    expect(defaultValue.value).toBe(20)

    defaultValue.value = 100
    await nextTick()
    expect(sessionValue.value).toBe(100)
    expect(onSynced).toHaveBeenCalledWith(100)
  })

  it('会话恢复期间可以拒绝迟到的默认值覆盖', async () => {
    const defaultValue = ref(20)
    const restoring = ref(true)
    const sessionValue = useDefaultedSessionValue(defaultValue, {
      shouldSync: () => !restoring.value,
    })

    sessionValue.value = 200
    defaultValue.value = 50
    await nextTick()
    expect(sessionValue.value).toBe(200)

    restoring.value = false
    defaultValue.value = 100
    await nextTick()
    expect(sessionValue.value).toBe(100)
  })
})
