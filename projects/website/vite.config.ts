import type { IncomingMessage, ServerResponse } from 'node:http'
import path from 'node:path'
import type { Plugin } from 'vite'
import { defineConfig } from 'vitest/config'
import { palettePlugin } from './src/palette-plugin'

/**
 * nginx maps `/privacy` to `/privacy.html` in production (projects/website/deploy/nginx.conf).
 * Vite's dev and preview servers do not, so an extensionless link that works in
 * production 404s locally -- and the E2E suite would then have to navigate to paths
 * no visitor ever uses, which is a suite that tests something else. This makes all
 * three agree.
 */
function extensionlessHtml(): Plugin {
  function rewrite(req: IncomingMessage, _res: ServerResponse, next: () => void): void {
    const [pathname = '/', query] = (req.url ?? '/').split('?')
    // `/api/` is the proxy's, never a page: rewriting it would post the form to
    // `/api/orbiters/signups.html`, which the API rightly does not have.
    if (pathname !== '/' && !pathname.includes('.') && !pathname.startsWith('/api/')) {
      req.url = `${pathname}.html${query ? `?${query}` : ''}`
    }
    next()
  }
  return {
    name: 'website-extensionless-html',
    configureServer(server) {
      server.middlewares.use(rewrite)
    },
    configurePreviewServer(server) {
      server.middlewares.use(rewrite)
    },
  }
}

const apiUrl = process.env.WEBSITE_API_URL ?? 'http://localhost:8000'

export default defineConfig({
  root: path.resolve(__dirname, 'src'),
  // Absolute, not './': nginx serves these three files from the document root, and
  // /privacy is one path segment deep only by URL, not by directory. A relative
  // base would still work here, but it would break the moment a page moved.
  base: '/',
  // No React, no Tailwind, no TanStack router plugin. That absence is the
  // requirement, not an omission: spec 9.4 exists so these pages do not drag the
  // application's bundle behind it.
  plugins: [palettePlugin(), extensionlessHtml()],
  build: {
    outDir: path.resolve(__dirname, 'dist'),
    emptyOutDir: true,
    // field.js is shared by the landing page and Orbiters; inlining it would put a copy
    // inside two HTML files instead of one cacheable asset.
    assetsInlineLimit: 0,
    rollupOptions: {
      input: {
        index: path.resolve(__dirname, 'src/index.html'),
        privacy: path.resolve(__dirname, 'src/privacy.html'),
        termini: path.resolve(__dirname, 'src/termini.html'),
        orbiters: path.resolve(__dirname, 'src/orbiters.html'),
      },
    },
  },
  // The Orbiters form posts to /api/orbiters/signups on the same origin, exactly as
  // nginx serves it in production. Dev and preview proxy that one prefix to a running
  // API so the form can be exercised locally; WEBSITE_API_URL points it elsewhere.
  server: { proxy: { '/api': { target: apiUrl, changeOrigin: true } } },
  preview: { port: 4173, strictPort: true, proxy: { '/api': { target: apiUrl, changeOrigin: true } } },
  // The suite reads the built and unbuilt files off disk and asserts on their text:
  // which tokens a sheet is allowed to declare, what each page's markup promises, how
  // the field behaves. `jsdom` is here for the two files that construct elements;
  // nothing renders a framework, because there is no framework.
  test: { environment: 'jsdom', globals: true },
})
