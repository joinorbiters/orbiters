import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeEach, describe, expect, it } from 'vitest'

const source = readFileSync(join(__dirname, 'field.js'), 'utf-8')

type FieldWindow = Window & {
  __pigroField?: {
    noise: (x: number, y: number) => number
    diagonal: (u: number, v: number) => number
    mount: (canvas: HTMLCanvasElement, options?: object) => void
  }
}

function load() {
  new Function(source)()
  const api = (window as FieldWindow).__pigroField
  if (!api) throw new Error('field.js did not expose window.__pigroField')
  return api
}

describe('field.js', () => {
  beforeEach(() => {
    delete (window as FieldWindow).__pigroField
  })

  it('stays small', () => {
    // Commented source; Vite ships it under 2 KB. It is loaded by two pages.
    expect(Buffer.byteLength(source, 'utf-8')).toBeLessThan(5 * 1024)
  })

  it('makes no request and carries no colour of its own', () => {
    expect(source).not.toMatch(/fetch\(|XMLHttpRequest|import\s|require\(/)
    expect(source).not.toMatch(/localStorage|sessionStorage|document\.cookie|navigator\.sendBeacon/)
    expect(source).not.toMatch(/#[0-9a-fA-F]{6}\b/)
    expect(source).toMatch(/--color-prussian-blue/)
  })

  it('noise is deterministic and stays in [0, 1)', () => {
    const api = load()
    for (const [x, y] of [
      [0.2, 0.7],
      [3.4, 9.1],
      [100.5, 0.25],
      [-4.2, 7.9],
    ]) {
      const a = api.noise(x!, y!)
      expect(a).toBe(api.noise(x!, y!))
      expect(a).toBeGreaterThanOrEqual(0)
      expect(a).toBeLessThan(1)
    }
  })

  it('the default band is a diagonal that empties out at the corners', () => {
    const api = load()
    expect(api.diagonal(0.5, 0.5)).toBe(1)
    expect(api.diagonal(0, 0)).toBeLessThanOrEqual(0)
    expect(api.diagonal(1, 1)).toBeLessThanOrEqual(0)
  })

  it('never starts the loop when the reader asked for less motion', () => {
    expect(source).toMatch(/prefers-reduced-motion: reduce/)
    expect(source).toMatch(/if \(!options\.animate \|\| reduced\) return/)
  })

  it('does nothing on a canvas with no 2d context, rather than throwing', () => {
    // jsdom has no canvas implementation, which is exactly the case to survive.
    const api = load()
    const canvas = document.createElement('canvas')
    expect(() => api.mount(canvas, { cell: 16 })).not.toThrow()
  })
})
