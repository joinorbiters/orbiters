import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Plugin } from 'vite'

/**
 * The path map, as the dev and preview servers serve it.
 *
 * Production is `deploy/nginx.conf`, inside the website's own image: four exact
 * extensionless paths, one redirect, the hashed assets, and a 404 for everything else.
 * Vite's servers know none of that on their own. Left alone they fall back to
 * `index.html` with a 200 for any path that resolves to no file, so a link nobody
 * serves passes the suite locally and 404s in production (ORB-21); and until
 * 2026-09-11 `/` was the community page, not `index.html`, so they served the wrong
 * page at the front door as well (ORB-145 put the landing there). This module says the same thing
 * nginx says, once more, in the shape of a middleware; `path-map-plugin.test.ts` reads
 * `deploy/nginx.conf` and fails when the two copies disagree, which is the only way
 * two copies of anything stay equal.
 */

/** `location = <path> { try_files <file> =404; }`, one line each in nginx.conf. */
export const PAGES: Readonly<Record<string, string>> = {
  '/': '/index.html',
  '/pigrocrm': '/pigrocrm.html',
  '/orbiters': '/orbiters.html',
  '/pitch': '/pitch.html',
  '/privacy': '/privacy.html',
  '/termini': '/termini.html',
}

/** `location = <path> { return 301 <to>; }`. nginx's `return` drops the query string
 *  and so does this. */
export const REDIRECTS: Readonly<Record<string, string>> = {}

/**
 * Paths the host's vhost (`deploy/joinorbiters.conf`) hands to other tenants of the
 * origin before the website container ever sees them. The container 404s them; a
 * visitor never does. A Vite server cannot run those tenants, so it does the one
 * honest thing short of pretending: `/api` is proxied to a running API so the form can
 * be exercised, and the rest answer a plain-text stand-in that says where production
 * sends them. Not a redirect on purpose: `/app` goes to another domain, and a suite
 * that followed it would be testing the CRM's uptime.
 */
export const ELSEWHERE: Readonly<Record<string, string>> = {
  '/api': 'the Orbiters hub API (projects/hub), proxied here to WEBSITE_API_URL',
  '/hub': 'the Orbiters hub SPA (projects/hub)',
  '/app': 'PigroCRM, a 302 to https://pigro.joinorbiters.com',
  '/health': "the hub API's probe",
}

export type Route =
  | { kind: 'page'; file: string }
  | { kind: 'redirect'; to: string }
  | { kind: 'proxy' }
  | { kind: 'elsewhere'; owner: string }
  | { kind: 'file' }
  | { kind: 'not-found' }

function underPrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`)
}

/** What the server does with one request path (no query string). Pure, so the unit
 *  test can walk the whole map without a server. */
export function route(pathname: string): Route {
  const redirect = REDIRECTS[pathname]
  if (redirect !== undefined) return { kind: 'redirect', to: redirect }
  const file = PAGES[pathname]
  if (file !== undefined) return { kind: 'page', file }
  for (const [prefix, owner] of Object.entries(ELSEWHERE)) {
    if (underPrefix(pathname, prefix)) return prefix === '/api' ? { kind: 'proxy' } : { kind: 'elsewhere', owner }
  }
  // nginx serves a page only under the name above it, never as `/privacy.html`.
  if (pathname.endsWith('.html')) return { kind: 'not-found' }
  // Anything with an extension is a file: `/assets/*` in preview, exactly as nginx has
  // it, plus the sources and Vite's own client (`/@vite/client`, `/@fs/...`) in dev. A
  // file that does not exist still 404s, because `appType: 'mpa'` in vite.config.ts
  // turned the index.html fallback off.
  if (pathname.includes('.') || pathname.startsWith('/@')) return { kind: 'file' }
  return { kind: 'not-found' }
}

function handle(req: IncomingMessage, res: ServerResponse, next: () => void): void {
  const [pathname = '/', query] = (req.url ?? '/').split('?')
  const decision = route(pathname)
  switch (decision.kind) {
    case 'redirect':
      res.statusCode = 301
      res.setHeader('Location', decision.to)
      res.end()
      return
    case 'page':
      req.url = `${decision.file}${query ? `?${query}` : ''}`
      next()
      return
    case 'elsewhere':
      res.statusCode = 200
      res.setHeader('Content-Type', 'text/plain; charset=utf-8')
      res.end(
        `${pathname} is not served by projects/website. In production it belongs to ${decision.owner}; see deploy/joinorbiters.conf.\n`,
      )
      return
    case 'not-found':
      res.statusCode = 404
      res.setHeader('Content-Type', 'text/plain; charset=utf-8')
      res.end(
        `404 Not Found: ${pathname} is in neither path map (deploy/nginx.conf, src/path-map-plugin.ts).\n`,
      )
      return
    case 'proxy':
    case 'file':
      next()
  }
}

export function pathMapPlugin(): Plugin {
  return {
    name: 'website-path-map',
    // Plugin middlewares are installed before Vite's own, the proxy included, on both
    // servers; that is what lets this decide `/` before the html fallback does.
    configureServer(server) {
      server.middlewares.use(handle)
    },
    configurePreviewServer(server) {
      server.middlewares.use(handle)
    },
  }
}
