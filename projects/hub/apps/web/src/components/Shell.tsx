import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { BrandMark } from '@/components/BrandMark'

/** The public frame: the mark and the name up top, the two legal links at the foot, and
 *  one white panel in between -- the CRM's panel, without its sidebar. */
export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-col">
      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-5">
        <Link to="/" className="inline-flex items-center gap-2.5 text-lg font-semibold tracking-tight">
          <BrandMark className="size-3.5" />
          Orbiters
        </Link>
        <a
          className="text-sm text-muted-foreground underline-offset-2 hover:underline"
          href="https://joinorbiters.com/"
        >
          joinorbiters.com
        </a>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 pb-12">
        <div className="rounded-2xl border bg-card px-6 py-10 shadow-xs sm:px-10">{children}</div>
      </main>
      <footer className="mx-auto flex w-full max-w-5xl flex-wrap gap-4 px-6 pb-8 text-xs text-muted-foreground">
        <a href="https://joinorbiters.com/privacy" className="underline-offset-2 hover:underline">
          Privacy
        </a>
        <a href="https://joinorbiters.com/termini" className="underline-offset-2 hover:underline">
          Termini
        </a>
        <span>Orbiters è un progetto di Humancraft di Ivan Sala</span>
      </footer>
    </div>
  )
}
