import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { BrandMark } from '@/components/BrandMark'

/** The public frame: the mark and the name up top, the two legal links and the
 *  attribution at the foot, one boxed panel in between -- the site's own visual
 *  system (ORB-73's `.site` scope) rather than the application's, so a visitor who
 *  clicked a CTA on joinorbiters.com does not land on a different product. `site`
 *  also carries the page's ground (the same faint grid the landing sits on), and the
 *  panel is centred in the space between header and footer instead of sitting at the
 *  top of an empty page: `justify-center` on `main` only has room to act when the
 *  step is shorter than the viewport, which is the common case here. Each link over
 *  the grid keeps a sliver of the page's own surface behind it, the same treatment
 *  `landing.css`'s `.top a` and `footer .quiet-link` give theirs. */
export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="site flex min-h-full flex-col">
      <header className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-y-2 px-6 py-5">
        <Link
          to="/"
          className="inline-flex items-center gap-2.5 bg-[var(--landing-surface)] p-[var(--landing-link-pad)] text-lg font-medium tracking-tight"
        >
          <BrandMark className="size-3.5" />
          Orbiters
        </Link>
        <nav className="flex items-center gap-4 text-sm">
          <Link to="/io" className="text-muted-foreground underline-offset-2 hover:underline">
            La tua area
          </Link>
          <a
            className="text-muted-foreground underline-offset-2 hover:underline"
            href="https://joinorbiters.com/"
          >
            joinorbiters.com
          </a>
        </nav>
      </header>
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col items-center justify-center px-6 py-12">
        <div className="w-full border-[length:var(--landing-border-width)] bg-card px-6 py-10 shadow-xs sm:px-10">
          {children}
        </div>
      </main>
      <footer className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-6 border-t-[length:var(--landing-border-width)] px-6 py-8 text-xs text-muted-foreground">
        <a
          href="https://joinorbiters.com/privacy"
          className="bg-[var(--landing-surface)] p-[var(--landing-link-pad)] underline-offset-2 hover:underline"
        >
          Privacy
        </a>
        <a
          href="https://joinorbiters.com/termini"
          className="bg-[var(--landing-surface)] p-[var(--landing-link-pad)] underline-offset-2 hover:underline"
        >
          Termini
        </a>
        {/* The same attribution the landing's own footer carries, in the same shape
            and pointing at the same host (ORB-116). Two footers that disagree is how
            this one ended up naming a test fixture in production for a week (ORB-97),
            so when one changes the other changes with it. */}
        <a
          href="https://humancraft.tech/"
          className="bg-[var(--landing-surface)] p-[var(--landing-link-pad)] underline-offset-2 hover:underline"
        >
          Humancraft
        </a>
      </footer>
    </div>
  )
}
