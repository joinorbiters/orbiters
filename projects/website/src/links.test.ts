import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { REDIRECTS, route } from './path-map-plugin'

/**
 * ORB-66: nothing else in the suite resolves an `<a href>` against what the site
 * actually serves. `path-map-plugin.ts`'s `route()` is the one function that already
 * knows the answer for an internal path -- it is what the dev and preview servers run
 * on every request, and `path-map-plugin.test.ts` keeps it equal to `deploy/nginx.conf`
 * -- so this file reuses it rather than growing a second opinion about which paths
 * exist.
 *
 * What this deliberately does not check, and why:
 *
 * - External links (`https://...`) are checked for shape (a parseable absolute URL)
 *   and for host (an explicit allowlist), never fetched: a test that curls another
 *   site's server fails on a machine with no network and on a day that site is down,
 *   for a reason this repository did nothing to cause. The GitHub link in index.html
 *   is the case worth naming: `.../blob/main/projects/pigrocrm/README.md#deploy`
 *   happens to point at a file this very checkout carries, but the `#deploy` fragment
 *   is a heading slug GitHub's own renderer computes when it displays the file, not
 *   anything this repository's build produces or serves. Verifying it would mean
 *   reimplementing GitHub's markdown-to-anchor algorithm to check a target nothing
 *   here emits, for a link that is still, mechanically, external. That is exactly the
 *   class of bug behind ORB-65's dead `#installazione` anchor (a GitHub link, on a
 *   repository that no longer existed under that name, fixed by hand): a fragment into
 *   another repository or another product's README cannot be verified locally, so the
 *   host allowlist plus a human glance (recorded in the PR) is the whole check, on
 *   purpose, both before and after that fix.
 * - `mailto:` links point at an address, not a page this site serves, so they carry no
 *   route to resolve.
 * - A link that resolves through `REDIRECTS` is treated as wrong, not merely checked
 *   for a working target. `REDIRECTS` exists for a bookmark or an inbound link this
 *   site does not control (`/orbiters`, from before the community page took `/`);
 *   markup this build produces itself should say what it means directly. That rule is
 *   what the three links this issue names actually trip: none of them 404, all three
 *   still 301 to a page that exists, and all three are "wrong" only in that sense,
 *   which is exactly why nothing before this test noticed them.
 * - A path under `ELSEWHERE` (`/app/`, `/hub/...`) resolves to another tenant of the
 *   origin, named in `deploy/joinorbiters.conf` and served by a container this suite
 *   never runs, so the check stops at "the path map hands it away" and does not, and
 *   cannot, follow it further.
 */

const PAGE_FILES = ['index.html', 'orbiters.html', 'privacy.html', 'termini.html'] as const
type PageFile = (typeof PAGE_FILES)[number]

const SRC_DIR = join(__dirname)
const html: Record<PageFile, string> = Object.fromEntries(
  PAGE_FILES.map((name) => [name, readFileSync(join(SRC_DIR, name), 'utf-8')]),
) as Record<PageFile, string>

/** Every `id="..."` in a page, as the set of fragments it can be linked to. Exercised
 *  directly below, since no page currently links to an in-page anchor to exercise it
 *  through the check itself. */
function idsOn(page: string): Set<string> {
  return new Set([...page.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]!))
}

/** The site's own trusted external destinations. Mirrors the allowlist
 *  `landing-pages.test.ts`'s "requests nothing from another origin" test already
 *  enforces for `href`/`src` subresources, kept as its own list here because that
 *  file does not cover `orbiters.html`, and because an `<a>` a visitor clicks is a
 *  different concern from a subresource the page fetches for itself: this list is
 *  free to diverge from that one without either test lying about what it guarantees.
 *  No `example.com` here on purpose: it is the host the suite's fixtures use, and a link
 *  to it on a page is a fixture that leaked into the markup (ORB-116, after ORB-97 on
 *  the hub). */
const EXTERNAL_HOSTS = ['github.com', 'pigro.joinorbiters.com', 'openai.com', 'humancraft.tech']

function checkExternal(href: string): string | undefined {
  let url: URL
  try {
    url = new URL(href)
  } catch {
    return `${href} is not a parseable absolute URL`
  }
  if (url.protocol !== 'https:') return `${href} is not https`
  if (!EXTERNAL_HOSTS.includes(url.hostname)) return `${href} is not on an allowed host`
  return undefined
}

/** Resolves one internal path (no fragment, no query string) against the path map,
 *  applying the redirect-is-wrong rule from the file comment above. */
function checkInternalPath(pathname: string): string | undefined {
  const result = route(pathname)
  if (result.kind === 'not-found') return `${pathname} is not served: the path map 404s it`
  if (result.kind === 'redirect') {
    return `${pathname} is a redirect to ${result.to}; link to ${result.to} directly instead of through the redirect`
  }
  // route() calls anything with a dot a "file" without checking it exists (that is
  // what lets a hashed build asset through in preview); a source-tree check is not
  // proof of a built one, but it does catch a plain typo in a link to a static asset.
  if (result.kind === 'file' && !existsSync(join(SRC_DIR, pathname))) {
    return `${pathname} is not served: no file under src/ answers it`
  }
  return undefined
}

/** Resolves one `<a href>` from `pageFile`, returning a failure reason or undefined. */
function checkHref(pageFile: PageFile, href: string): string | undefined {
  if (href.startsWith('mailto:')) return undefined
  if (href.startsWith('#')) {
    const id = href.slice(1)
    return idsOn(html[pageFile]).has(id) ? undefined : `${href}: no id="${id}" on ${pageFile}`
  }
  if (/^https?:\/\//.test(href)) return checkExternal(href)
  if (href.startsWith('/')) {
    // route() -- and the middleware built on it -- both drop the query string before
    // matching a path; the same has to happen here, or a page's own campaign link to
    // itself (e.g. "?utm_source=...") 404s in this check while nginx serves it fine.
    const [pathWithoutQuery] = href.split('?') as [string]
    const [pathname, fragment] = pathWithoutQuery.split('#') as [string, string | undefined]
    const pathFailure = checkInternalPath(pathname)
    if (pathFailure) return pathFailure
    if (fragment === undefined) return undefined
    const result = route(pathname)
    if (result.kind !== 'page') {
      return `${href}: ${pathname} is not one of this site's own pages, so its fragment cannot be checked here`
    }
    const targetFile = result.file.replace(/^\//, '') as PageFile
    return idsOn(html[targetFile] ?? '').has(fragment) ? undefined : `${href}: no id="${fragment}" on ${targetFile}`
  }
  // A scheme this file does not otherwise recognise (tel:, sms:, data:, javascript:,
  // ...) is not a page this site serves either, for the same reason mailto: above is
  // skipped rather than resolved.
  if (/^[a-z][a-z0-9+.-]*:/i.test(href)) return undefined
  // A relative reference (e.g. "./file.pdf"), resolved against this project's src/ the
  // way a browser resolves it against the page: it has to exist on disk. None of the
  // four pages' <a> tags use one today; this is the fallback for the day one does.
  return existsSync(join(SRC_DIR, href)) ? undefined : `${href} does not exist relative to ${pageFile}`
}

describe('REDIRECTS resolve to something real', () => {
  it('sends every redirect target somewhere the path map does not 404', () => {
    for (const [from, to] of Object.entries(REDIRECTS)) {
      expect(route(to).kind, `${from} -> ${to}`).not.toBe('not-found')
    }
  })
})

describe.each(PAGE_FILES)('%s', (name) => {
  it('links only to what the site actually serves', () => {
    const hrefs = [...html[name].matchAll(/<a\s[^>]*\bhref="([^"]+)"/g)].map((m) => m[1]!)
    const failures = hrefs.map((href) => checkHref(name, href)).filter((reason): reason is string => reason !== undefined)
    expect(failures).toEqual([])
  })
})

describe('idsOn, the id-extraction helper behind the fragment check', () => {
  // No page currently links to an in-page anchor, so this is proven directly on the
  // helper `checkHref` calls for a "#fragment" href, rather than through a page fixture
  // that does not exist yet.
  it('finds an id declared anywhere in the markup, and only that id', () => {
    const page = '<h2 id="come-funziona">Come funziona</h2>'
    expect(idsOn(page).has('come-funziona')).toBe(true)
    expect(idsOn(page).has('altro')).toBe(false)
  })
})

describe('checkHref, edge cases none of the four pages exercise today', () => {
  it('catches a mistyped absolute asset path, and passes the real one', () => {
    expect(checkHref('index.html', '/orbiters-logo.svg')).toBeUndefined()
    expect(checkHref('index.html', '/orbiter-logo.svg')).toMatch(/no file under src\/ answers it/)
  })

  it('drops the query string before routing, like the dev server does', () => {
    expect(checkHref('index.html', '/privacy?utm_source=newsletter')).toBeUndefined()
    // The redirect-is-wrong rule still applies once the query string is gone.
    expect(checkHref('index.html', '/orbiters?utm_source=newsletter')).toMatch(/is a redirect to \//)
  })

  it('skips a scheme it does not otherwise resolve, the same way it skips mailto:', () => {
    expect(checkHref('index.html', 'tel:+390000000')).toBeUndefined()
    expect(checkHref('index.html', 'javascript:void(0)')).toBeUndefined()
  })
})
