import type { IncomingMessage, ServerResponse } from 'node:http'
import path from 'node:path'
import { defineConfig, type Plugin } from 'vite'
import { palettePlugin } from './landing/palette-plugin'

/**
 * nginx maps `/privacy` to `/privacy.html` in production (deploy/nginx/spa.conf).
 * Vite's dev and preview servers do not, so an extensionless link that works in
 * production 404s locally -- and the E2E suite would then have to navigate to paths
 * no visitor ever uses, which is a suite that tests something else. This makes all
 * three agree.
 */
function extensionlessHtml(): Plugin {
  function rewrite(req: IncomingMessage, _res: ServerResponse, next: () => void): void {
    const [pathname = '/', query] = (req.url ?? '/').split('?')
    if (pathname !== '/' && !pathname.includes('.')) {
      req.url = `${pathname}.html${query ? `?${query}` : ''}`
    }
    next()
  }
  return {
    name: 'pigrocrm-landing-extensionless-html',
    configureServer(server) {
      server.middlewares.use(rewrite)
    },
    configurePreviewServer(server) {
      server.middlewares.use(rewrite)
    },
  }
}

export default defineConfig({
  root: path.resolve(__dirname, 'landing'),
  // Absolute, not './': nginx serves these three files from the document root, and
  // /privacy is one path segment deep only by URL, not by directory. A relative
  // base would still work here, but it would break the moment a page moved.
  base: '/',
  // No React, no Tailwind, no TanStack router plugin. That absence is the
  // requirement, not an omission: spec 9.4 exists so the landing does not drag the
  // application's bundle behind it.
  plugins: [palettePlugin(), extensionlessHtml()],
  build: {
    outDir: path.resolve(__dirname, 'dist-landing'),
    emptyOutDir: true,
    // The pages have no shared JS chunk to speak of, and inlining the ~1 KB of
    // reveal.js would put it inside three HTML files instead of one cacheable one.
    assetsInlineLimit: 0,
    rollupOptions: {
      input: {
        index: path.resolve(__dirname, 'landing/index.html'),
        privacy: path.resolve(__dirname, 'landing/privacy.html'),
        termini: path.resolve(__dirname, 'landing/termini.html'),
      },
    },
  },
  preview: { port: 4173, strictPort: true },
})
