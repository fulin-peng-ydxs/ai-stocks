import { reactive } from 'vue'
import { describe, expect, it } from 'vitest'
import { useFormChangeTracker } from '@/composables/useFormChangeTracker'

describe('useFormChangeTracker', () => {
  it('记录基线前和内容未变化时不可保存，变化后允许保存', () => {
    const form = reactive({ name: '方案', nested: { enabled: true } })
    const tracker = useFormChangeTracker(() => form)

    expect(tracker.hasChanges.value).toBe(false)
    tracker.captureBaseline()
    expect(tracker.hasChanges.value).toBe(false)

    form.nested.enabled = false
    expect(tracker.hasChanges.value).toBe(true)
    tracker.captureBaseline()
    expect(tracker.hasChanges.value).toBe(false)
  })

  it('对象字段顺序变化不产生伪变更，数组顺序仍视为内容变化', () => {
    const state = reactive<{ value: unknown }>({ value: { a: 1, b: 2 } })
    const tracker = useFormChangeTracker(() => state.value)
    tracker.captureBaseline()

    state.value = { b: 2, a: 1 }
    expect(tracker.hasChanges.value).toBe(false)

    state.value = [1, 2]
    tracker.captureBaseline()
    state.value = [2, 1]
    expect(tracker.hasChanges.value).toBe(true)
  })

  it('清除基线后重新进入初始化保护态', () => {
    const form = reactive({ name: '方案' })
    const tracker = useFormChangeTracker(() => form)
    tracker.captureBaseline()
    form.name = '新方案'
    expect(tracker.hasChanges.value).toBe(true)

    tracker.clearBaseline()
    expect(tracker.hasChanges.value).toBe(false)
  })
})
