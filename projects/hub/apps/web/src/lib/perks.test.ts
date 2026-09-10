import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { GUIDE } from './perks'

const lock = JSON.parse(
  readFileSync(join(__dirname, '..', '..', '..', '..', 'tools', 'guide-pdf.lock.json'), 'utf-8'),
) as { bytes: number; pages: number }

describe('the numbers the member area shows beside the guide', () => {
  it('are the file the API serves, not a memory of it', () => {
    // The card promises "PDF, 6 pagine, 48 KB" before anybody clicks. A guide that grows
    // by a page fails here until the card says so, which is the only reason writing the
    // numbers into a component is acceptable at all.
    expect(GUIDE.pages).toBe(lock.pages)
    expect(GUIDE.kilobytes).toBe(Math.round(lock.bytes / 1024))
  })
})
