import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { daysAgo, formatDateTime, today } from './date'

describe('date utils', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('today 返回本地日期，不受 UTC 偏移影响', () => {
    vi.setSystemTime(new Date(2026, 10, 18, 0, 30, 0))
    expect(today()).toBe('2026-11-18')
  })

  it('daysAgo 正确跨月', () => {
    vi.setSystemTime(new Date(2026, 10, 18, 12, 0, 0))
    expect(daysAgo(31)).toBe('2026-10-18')
  })

  it('daysAgo 正确跨年', () => {
    vi.setSystemTime(new Date(2026, 0, 5, 12, 0, 0))
    expect(daysAgo(10)).toBe('2025-12-26')
  })

  it('formatDateTime 处理空值与 ISO 字符串', () => {
    expect(formatDateTime()).toBe('')
    expect(formatDateTime(null)).toBe('')
    expect(formatDateTime('2026-11-09T09:08:02.000Z')).toBe('2026-11-09 09:08:02')
    expect(formatDateTime('2026-11-09T09:08:02Z')).toBe('2026-11-09 09:08:02')
    expect(formatDateTime('2026-11-09')).toBe('2026-11-09')
  })
})
