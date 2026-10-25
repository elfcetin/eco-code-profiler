import { describe, expect, it } from 'vitest'
import { formatSeconds, formatSpeedup } from '../format.js'

describe('formatSeconds', () => {
  it.each([
    [null, '—'],
    [0, '<1 ns'],
    [4e-10, '<1 ns'],
    [2.9e-7, '290 ns'],
    [9.99e-7, '999 ns'],
    [4.33e-6, '4,3 µs'],
    [2.36e-4, '236 µs'],
    [0.0074, '7,4 ms'],
    [1.5, '1,50 sn'],
  ])('%s -> %s', (seconds, text) => {
    expect(formatSeconds(seconds)).toBe(text)
  })

  it('1 µs altı hiçbir zaman "0 µs" olmaz', () => {
    for (const s of [0, 1e-9, 1e-8, 3e-7, 9e-7]) expect(formatSeconds(s)).not.toMatch(/^0 µs$/)
  })
})

describe('formatSpeedup', () => {
  it('büyük oranlar binlik ayraçla', () => {
    expect(formatSpeedup(1759.4)).toBe('1.759×')
    expect(formatSpeedup(2.04)).toBe('2,0×')
  })
})
