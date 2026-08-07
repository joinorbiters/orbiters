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
  {
    // `auth.tsx` is a deliberate, permanent context-provider bundle: `AuthProvider`
    // (the component) plus the three hooks that only make sense next to it
    // (`useAuth`, `useCanWrite`, `useIsAdmin`) -- one module, matching this file's
    // place in the plan's own File Structure and what later screens import from
    // `@/lib/auth`. That is exactly the shape `react-refresh/only-export-components`
    // flags (a component file also exporting non-component values), but splitting a
    // ~70-line auth module into two files purely to satisfy this rule would trade a
    // real, permanent indirection for a cost that is real but narrow: editing this
    // file forces a full remount of its subtree on save instead of a hot patch, and
    // this file changes rarely compared to the components actually iterated on.
    // `allowExportNames`, not a blanket `'off'`: the rule stays live for anything
    // added to this file later that is *not* one of these three known, intentional
    // exports -- an accidental new non-component export would still be caught.
    files: ['src/lib/auth.tsx'],
    rules: {
      // Same severity as the base `vite` preset ("error") -- only the options
      // change here, not how strictly the rule is enforced.
      'react-refresh/only-export-components': [
        'error',
        { allowConstantExport: true, allowExportNames: ['useAuth', 'useCanWrite', 'useIsAdmin'] },
      ],
    },
  },
])
