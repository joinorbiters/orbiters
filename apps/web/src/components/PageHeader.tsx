import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * The header of a page, inside the white panel (spec 2026-09-08 §4).
 *
 * It replaces the shell's top bar, which is gone: the search moved into the sidebar, and
 * what used to be a breadcrumb repeating the sidebar's own highlight is now the page's
 * title, at the size a title deserves. One `<h1>` per screen lives here.
 *
 * Four slots, in the order they are drawn: the title row (icon, title, description,
 * `actions`), then `tabs` on a row of their own closed by a rule, then `children` for
 * whatever a page needs between its header and its content -- a filter row, most often.
 * `actions` is where a page's primary button goes (§5: one strong thing per screen, top
 * right); everything else on the screen is quieter than it.
 */
export function PageHeader({
  icon: Icon,
  title,
  description,
  actions,
  tabs,
  children,
  className,
}: {
  icon: LucideIcon
  title: string
  description?: string
  actions?: ReactNode
  tabs?: ReactNode
  children?: ReactNode
  className?: string
}) {
  return (
    <header className={cn('shrink-0', className)}>
      <div className="flex items-start gap-4 px-6 pt-6 pb-5">
        {/* Paper square, 40px, radius 10: the one piece of colour in the header, and a
            fixed anchor the eye finds at the same spot on every page. Decorative -- it
            says what the title already says, so it is hidden from a screen reader. */}
        <span
          className="flex size-10 shrink-0 items-center justify-center rounded-[10px] bg-background text-foreground"
          aria-hidden="true"
        >
          <Icon className="size-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-2xl font-semibold tracking-tight">{title}</h1>
          {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>

      {tabs && <div className="border-b px-6">{tabs}</div>}
      {children}
    </header>
  )
}
