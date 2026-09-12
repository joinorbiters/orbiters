import { defineConfig } from 'vitest/config'

// `node`, not jsdom: `posthog-js` is mocked in every test here, and the one function
// that reads `window` is given the hostname by hand. The consumers test their own DOM.
export default defineConfig({ test: { environment: 'node', globals: true } })
