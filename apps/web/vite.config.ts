import { tanstackRouter } from '@tanstack/router-plugin/vite'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vite'
import { configDefaults } from 'vitest/config'

export default defineConfig({
  plugins: [
    tanstackRouter({
      target: 'react',
      autoCodeSplitting: true,
      // Without this, a `*.test.tsx` colocated next to a route file (the same
      // convention every other feature in this codebase already uses -- see
      // `routes/app/clienti/$customerId.test.tsx` and its two siblings) is scanned
      // as a route candidate too, and warns on every dev/build/test run ("does not
      // export a Route") since it obviously does not export one. A raw regex
      // source string, matched against the bare filename (confirmed by reading
      // `@tanstack/router-generator`'s own `getRouteNodes`), not a glob.
      routeFileIgnorePattern: '\\.test\\.tsx$',
    }),
    react(),
    tailwindcss(),
  ],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    port: 5173,
    // The browser talks to the same origin in dev and in production, so cookies
    // behave identically in both and there is no CORS special case to debug.
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.ts',
    // `apps/web/e2e/*.spec.ts` (Playwright, run via `playwright.config.ts`/
    // `pnpm exec playwright test`) match Vitest's own default include glob
    // just as well as any `*.test.tsx` here does -- confirmed live: without
    // this, `pnpm vitest run` picked up all six Playwright files and failed
    // each one immediately (`test.beforeEach()`/`test()` "did not expect ...
    // to be called here", Playwright's own guard against its globals leaking
    // into a foreign runner). `configDefaults.exclude` is spread back in
    // because `test.exclude` *replaces* Vitest's own default list rather than
    // adding to it -- dropping that spread would silently stop ignoring
    // node_modules/dist/etc. The two suites stay genuinely separate (task-10's
    // own requirement) rather than merely usually-not-colliding by luck of
    // file naming.
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})
