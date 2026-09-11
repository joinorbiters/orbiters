import { describe, expect, it } from 'vitest'
import { slugProblem, slugify, tenantPrefixFrom } from './tenant'

describe('the space prefix', () => {
  it('is read from /<slug>/app/... and nothing else', () => {
    expect(tenantPrefixFrom('/studio/app/clienti/abc')).toBe('/studio')
    expect(tenantPrefixFrom('/studio/app')).toBe('/studio')
    expect(tenantPrefixFrom('/app/clienti')).toBe('')
    expect(tenantPrefixFrom('/')).toBe('')
    expect(tenantPrefixFrom('/studio/clienti')).toBe('')
  })

  it('never mistakes a reserved word or a malformed segment for a space', () => {
    expect(tenantPrefixFrom('/app/app/login')).toBe('')
    expect(tenantPrefixFrom('/Studio/app/login')).toBe('')
    expect(tenantPrefixFrom('/-x-/app/login')).toBe('')
    expect(tenantPrefixFrom('/mcp/app/login')).toBe('')
  })
})

describe('slugify', () => {
  it('matches the server rule', () => {
    expect(slugify('Studio Rossi')).toBe('studio-rossi')
    expect(slugify('  Caffè & Co.  ')).toBe('caffe-co')
    expect(slugify('ÀÉÎÕÜ')).toBe('aeiou')
    expect(slugify('x'.repeat(40))).toBe('x'.repeat(32))
  })
})

describe('slugProblem', () => {
  it('accepts a well-formed name', () => {
    expect(slugProblem('studio-rossi')).toBeNull()
  })

  it('refuses short, malformed and reserved names with a reason', () => {
    expect(slugProblem('ab')).toMatch(/almeno 3/)
    expect(slugProblem('Studio')).toMatch(/minuscole/)
    expect(slugProblem('app')).toMatch(/riservato/)
    expect(slugProblem('mcp')).toMatch(/riservato/)
  })
})
