import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { Plugin } from 'vite'

const TOKENS_CSS = resolve(__dirname, '../src/styles/tokens.css')

/** The palette, the font stack and the radius scale, and nothing else. Fifteen
 *  today; the count is asserted so that a token added to or removed from
 *  tokens.css is a failing test rather than a silently thinner landing. */
const EXPECTED_TOKEN_COUNT = 15

/**
 * Reads the custom properties `tokens.css` declares inside a `@theme` block and
 * that the landing can meaningfully use on its own.
 *
 * Why extraction and not an `@import`: the palette lives inside Tailwind v4's
 * `@theme` at-rule, whose literal hex values are what let the app generate
 * `bg-watermelon/50`-style utilities. Pointing `@theme` at `var()` indirections to
 * make the block shareable would break that. The landing has no Tailwind at all, so
 * it cannot consume `@theme` either way. Copying the six hexes into `landing.css`
 * is the obvious alternative and is exactly the fork this function exists to make
 * impossible: there is one source of colour, and a landing built from a stale copy
 * of it cannot happen because no copy exists.
 *
 * The `var()` filter is what keeps `@theme inline`'s 26 semantic re-exports out.
 * They point at `--primary`, `--background` and friends, which live in
 * `tokens.css`'s `:root` and are the *app's* theme, not the shared system.
 */
export function extractSharedTokens(css: string): Record<string, string> {
  const collected: Record<string, string> = {}
  // tokens.css's two `@theme` blocks contain no nested braces, so a non-greedy
  // match up to the first `}` is exact here.
  for (const block of css.matchAll(/@theme[^{]*\{([^}]*)\}/g)) {
    for (const decl of (block[1] ?? '').matchAll(
      /(--(?:color|radius|font)[\w-]*)\s*:\s*([^;]+);/g,
    )) {
      const name = decl[1]
      const value = decl[2]
      if (name && value) collected[name] = value.trim()
    }
  }

  const names = new Set(Object.keys(collected))
  const shared: Record<string, string> = {}
  for (const [name, value] of Object.entries(collected)) {
    const references = [...value.matchAll(/var\((--[\w-]+)\)/g)].map((match) => match[1])
    if (references.every((reference) => reference !== undefined && names.has(reference))) {
      shared[name] = value
    }
  }

  const count = Object.keys(shared).length
  if (count !== EXPECTED_TOKEN_COUNT) {
    throw new Error(
      `extractSharedTokens extracted only ${count} shared token${count === 1 ? '' : 's'} ` +
        `from tokens.css (expected ${EXPECTED_TOKEN_COUNT}). The landing must not restate ` +
        'the palette: fix the extraction, do not paste values into landing.css.',
    )
  }
  return shared
}

/** Prepends the shared tokens to `landing/landing.css`, at build and at dev time. */
export function palettePlugin(): Plugin {
  return {
    name: 'pigrocrm-landing-palette',
    enforce: 'pre',
    transform(code, id) {
      if (!id.split('?')[0]?.endsWith('landing/landing.css')) return null
      const tokens = extractSharedTokens(readFileSync(TOKENS_CSS, 'utf-8'))
      const block = Object.entries(tokens)
        .map(([name, value]) => `  ${name}: ${value};`)
        .join('\n')
      return `/* injected from src/styles/tokens.css by palette-plugin.ts */\n:root {\n${block}\n}\n\n${code}`
    },
  }
}
