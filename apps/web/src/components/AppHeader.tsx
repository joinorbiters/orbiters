import { useRouterState } from '@tanstack/react-router'
import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { breadcrumbFor } from '@/components/breadcrumb'

/**
 * The top bar slice 1 §10.1 promised and `AppShell` never had. Three regions:
 * breadcrumb on the left, the search control in the middle, actions on the right.
 *
 * The actions region is deliberately empty today. It exists as a slot because the
 * alternative is a two-region header that has to be restructured the first time anything
 * needs to sit there, and because the sidebar already owns the account menu.
 */

// `metaKey` on Apple platforms, `ctrlKey` elsewhere. Read once at module scope from the
// platform hint rather than sniffing the user agent string: this only decides which glyph
// is drawn, and Task A13's listener accepts either modifier regardless.
const IS_APPLE =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform ?? '')

export function AppHeader({ onOpenSearch }: { onOpenSearch: () => void }) {
  const { location } = useRouterState()
  const crumbs = breadcrumbFor(location.pathname)

  return (
    <header
      role="banner"
      className="flex h-14 shrink-0 items-center gap-4 border-b bg-card px-6"
    >
      <nav aria-label="Percorso" className="min-w-0 flex-1">
        <ol className="flex items-center gap-2 text-sm text-muted-foreground">
          {crumbs.map((crumb, index) => (
            <li key={`${crumb}-${index}`} className="flex items-center gap-2">
              {index > 0 && <span aria-hidden="true">/</span>}
              <span
                className={index === crumbs.length - 1 ? 'truncate text-foreground' : 'truncate'}
                aria-current={index === crumbs.length - 1 ? 'page' : undefined}
              >
                {crumb}
              </span>
            </li>
          ))}
        </ol>
      </nav>

      <Button
        variant="outline"
        onClick={onOpenSearch}
        // A button and not an <input>: the palette is a dialog, so a real text field here
        // would take focus, accept typing, and then hand it over -- two places to type the
        // same query. One control, one place to type.
        className="w-full max-w-sm justify-between text-muted-foreground"
        aria-label="Cerca in tutto il CRM"
      >
        <span className="flex items-center gap-2">
          <Search className="size-4" aria-hidden="true" />
          Cerca…
        </span>
        <kbd className="rounded border bg-muted px-1.5 py-0.5 text-xs font-medium">
          {IS_APPLE ? '⌘' : 'Ctrl'} K
        </kbd>
      </Button>

      {/* Actions. Empty today; see the file docstring. */}
      <div className="flex flex-1 items-center justify-end gap-2" />
    </header>
  )
}
