import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { ELSEWHERE, PAGES, REDIRECTS, route } from './path-map-plugin'

const nginx = readFileSync(join(__dirname, '..', 'deploy', 'nginx.conf'), 'utf-8')
const vhost = readFileSync(join(__dirname, '..', 'deploy', 'joinorbiters.conf'), 'utf-8')

/** The exact-match locations of nginx.conf, as two maps shaped like the plugin's own. */
function nginxMap(conf: string): { pages: Record<string, string>; redirects: Record<string, string> } {
  const pages: Record<string, string> = {}
  const redirects: Record<string, string> = {}
  for (const [, path, file, to] of conf.matchAll(
    /^\s*location = (\S+)\s*\{\s*(?:try_files (\S+) =404|return 301 (\S+));\s*\}/gm,
  )) {
    if (file) pages[path!] = file
    if (to) redirects[path!] = to
  }
  return { pages, redirects }
}

describe('the path map, against deploy/nginx.conf', () => {
  it('serves the same file at each path nginx does, and no other', () => {
    expect(PAGES).toEqual(nginxMap(nginx).pages)
  })

  it('redirects the same paths to the same places', () => {
    expect(REDIRECTS).toEqual(nginxMap(nginx).redirects)
  })

  it('reads at least the four pages out of nginx.conf, so a reformatted file cannot pass as an empty map', () => {
    expect(Object.keys(nginxMap(nginx).pages).length).toBeGreaterThanOrEqual(4)
  })

  it('mirrors an nginx that 404s everything it was not told about', () => {
    expect(nginx).toMatch(/location \/ \{ return 404; \}/)
    expect(nginx).not.toMatch(/try_files \$uri \/index\.html/)
  })

  it('names only tenants the host vhost actually routes away from the container', () => {
    for (const prefix of Object.keys(ELSEWHERE)) {
      expect(vhost, `${prefix} in joinorbiters.conf`).toMatch(
        new RegExp(`^\\s*location\\s+(?:=|\\^~)?\\s*${prefix}[/\\s]`, 'm'),
      )
    }
  })
})

describe('route', () => {
  it('puts the landing at the front door and the community page under its old name (ORB-145)', () => {
    expect(route('/')).toEqual({ kind: 'page', file: '/index.html' })
    expect(route('/orbiters')).toEqual({ kind: 'page', file: '/orbiters.html' })
    expect(route('/pitch')).toEqual({ kind: 'page', file: '/pitch.html' })
    expect(route('/privacy')).toEqual({ kind: 'page', file: '/privacy.html' })
    expect(route('/termini')).toEqual({ kind: 'page', file: '/termini.html' })
  })

  it('sends /pigrocrm, where the landing lived until 2026-09-11, home to /', () => {
    expect(route('/pigrocrm')).toEqual({ kind: 'redirect', to: '/' })
  })

  it('404s what nginx 404s: unknown paths, trailing slashes, and the files under their own names', () => {
    for (const path of ['/nonexistent', '/pigrocrm/', '/privacy/', '/index.html', '/orbiters.html', '/privacy.html']) {
      expect(route(path), path).toEqual({ kind: 'not-found' })
    }
  })

  it('lets the built assets, the sources and the dev client through, with no html fallback behind them', () => {
    for (const path of ['/assets/landing-BwJRpj9t.css', '/orbiters.js', '/orbiters-logo.svg', '/@vite/client', '/@fs/x/y.ts']) {
      expect(route(path), path).toEqual({ kind: 'file' })
    }
  })

  it('proxies /api and answers a stand-in for the other tenants of the origin, whole prefixes only', () => {
    expect(route('/api/orbiters/signups')).toEqual({ kind: 'proxy' })
    expect(route('/app/')).toMatchObject({ kind: 'elsewhere' })
    expect(route('/app')).toMatchObject({ kind: 'elsewhere' })
    expect(route('/hub/freelance')).toMatchObject({ kind: 'elsewhere' })
    expect(route('/health')).toMatchObject({ kind: 'elsewhere' })
    // `/apple` is not `/app/`: a prefix match that ignored the slash would hand a real
    // 404 to a fictional tenant.
    expect(route('/apple')).toEqual({ kind: 'not-found' })
    expect(route('/hubris')).toEqual({ kind: 'not-found' })
  })
})
