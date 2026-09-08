/**
 * The tabs of the settings page, in the order they are shown.
 *
 * Its own module because two places need the same list and neither can own it:
 * `SettingsLayout` renders them as tabs, and `AppShell` renders them as the sub-items of
 * the «Impostazioni» group in the sidebar. Duplicating the labels meant the sidebar could
 * drift from the page silently -- a new tab appearing in one place and not the other --
 * which is exactly the kind of divergence a shared constant makes impossible.
 *
 * A plain `.ts` module rather than a second export from `SettingsLayout.tsx`: a component
 * file that also exports values trips `react-refresh/only-export-components`.
 *
 * The paths are *not* here: `<Link to>` typechecks against the generated route tree, so
 * the sidebar maps each `value` to a literal path of its own (`AppShell`'s
 * `SETTINGS_PATHS`), and adding a tab there is a compile error until the route exists.
 */
export const SETTINGS_TABS = [
  { value: 'spazio', label: 'Spazio' },
  { value: 'campi', label: 'Campi' },
  { value: 'pipeline', label: 'Pipeline' },
  { value: 'template', label: 'Template' },
  { value: 'emittente', label: 'Emittente' },
  { value: 'fiscale', label: 'Fiscale' },
  { value: 'utenti', label: 'Utenti' },
  { value: 'categorie-costo', label: 'Categorie costo' },
  { value: 'tariffe', label: 'Tariffe' },
  { value: 'periodi', label: 'Periodi' },
  { value: 'gmail', label: 'Gmail' },
  { value: 'drive', label: 'Google Drive' },
  { value: 'automazioni', label: 'Automazioni' },
] as const

export type SettingsTabValue = (typeof SETTINGS_TABS)[number]['value']
