import js from '@eslint/js'
import globals from 'globals'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

// No React, no Tailwind, no router plugin: the landing is four HTML pages and three
// scripts, and keeping it that way is the point of it being its own project rather
// than a corner of the application's bundle.
export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,js}'],
    extends: [js.configs.recommended, tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2022, globals: { ...globals.browser, ...globals.node } },
  },
])
