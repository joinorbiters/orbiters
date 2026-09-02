/**
 * The breadcrumb `AppHeader` renders, as a pure function of the pathname.
 *
 * Its own module rather than a second export from `AppHeader.tsx`: a component file that
 * also exports a plain function is what `react-refresh/only-export-components` flags, and
 * this one has no reason to live beside the component -- it takes a string and returns
 * strings, and its test asserts on those directly rather than through a rendered header.
 */

const SEGMENT_LABELS: Record<string, string> = {
  app: 'Dashboard',
  clienti: 'Clienti',
  persone: 'Persone',
  deal: 'Deal',
  documenti: 'Documenti',
  impostazioni: 'Impostazioni',
  campi: 'Campi',
  emittente: 'Emittente',
  pipeline: 'Pipeline',
  template: 'Template',
  utenti: 'Utenti',
  automazioni: 'Automazioni',
  token: 'Token',
  lista: 'Lista',
}

// A UUID segment is an id, not a name. Rendering it would put a 36-character opaque
// string in the breadcrumb, and resolving it to the record's title would mean a second
// request from a component whose job is navigation.
const UUID_SEGMENT =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/

export function breadcrumbFor(pathname: string): string[] {
  const segments = pathname.split('/').filter((segment) => segment.length > 0)
  if (segments.length === 0) return ['Dashboard']
  // Drop the leading "app": every authenticated route carries it and repeating it in
  // every breadcrumb is noise.
  const rest = segments[0] === 'app' ? segments.slice(1) : segments
  if (rest.length === 0) return ['Dashboard']
  return rest.map((segment) =>
    UUID_SEGMENT.test(segment)
      ? 'Dettaglio'
      : (SEGMENT_LABELS[segment] ?? segment.charAt(0).toUpperCase() + segment.slice(1)),
  )
}
