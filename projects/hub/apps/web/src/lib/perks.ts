/**
 * What the member area says about a perk's file before somebody clicks it.
 *
 * The two numbers are mirrored from `projects/hub/tools/guide-pdf.lock.json`, which the
 * generator writes off the PDF itself. Mirrored rather than imported: the lock sits two
 * projects' directories up, outside this app's Vite root, and a 48 KB download is not
 * worth teaching the dev server to serve files from outside it. `perks.test.ts` reads
 * the lock and fails when these drift, so the mirror cannot go stale quietly.
 */
export const GUIDE = {
  pages: 6,
  kilobytes: 48,
} as const
