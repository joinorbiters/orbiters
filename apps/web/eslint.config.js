import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
  {
    // shadcn generates these files verbatim; hand-editing them to satisfy lint
    // is pointless since the next `shadcn add --overwrite` puts them back as
    // the CLI's own template produces them. Both rules below flag a pattern
    // the generator itself ships on every relevant component — a file
    // exporting its component alongside its cva() variants function, and
    // useIsMobile's effect setting state synchronously off a media-query
    // listener — never an actual defect here. Scoped to exactly this file
    // set, not disabled project-wide.
    files: ['src/components/ui/**/*.{ts,tsx}', 'src/hooks/use-mobile.ts'],
    rules: {
      'react-refresh/only-export-components': 'off',
      'react-hooks/set-state-in-effect': 'off',
    },
  },
])
