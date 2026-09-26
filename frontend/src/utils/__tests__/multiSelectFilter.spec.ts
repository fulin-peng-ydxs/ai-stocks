import { describe, expect, it } from 'vitest'
import { isAllSelectedFilter, normalizeAllSelectedFilter } from '@/utils/multiSelectFilter'

const VALUES = ['主板', '创业板', '科创板', 'ST', '退市']

describe('multiSelectFilter', () => {
  it('treats empty and complete selections as the same canonical all state', () => {
    expect(normalizeAllSelectedFilter([], VALUES)).toEqual(VALUES)
    expect(normalizeAllSelectedFilter([...VALUES].reverse(), VALUES)).toEqual(VALUES)
  })

  it('keeps a partial selection in option order and drops unknown values', () => {
    expect(normalizeAllSelectedFilter(['ST', '主板', 'unknown'], VALUES)).toEqual(['主板', 'ST'])
  })

  it('recognizes the canonical all state regardless of order', () => {
    expect(isAllSelectedFilter([...VALUES].reverse(), VALUES)).toBe(true)
    expect(isAllSelectedFilter(['主板', 'ST'], VALUES)).toBe(false)
  })
})
