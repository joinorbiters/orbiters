# landing

joinorbiters.com: the Orbiters community page, the pages the product signs itself with
(`/pigrocrm`, `/privacy`, `/termini`), and the signup form.

Four HTML pages, three scripts, three stylesheets. No React, no Tailwind, no router.
That absence is the requirement rather than an omission: this is the first page a
visitor loads, and it does not drag an application bundle behind it. The build takes
about 300 milliseconds.

## Commands

```
pnpm --filter landing dev        # :5173, with /api proxied to a running CRM API
pnpm --filter landing build      # dist/
pnpm --filter landing test       # 99 assertions, vitest, no services
pnpm --filter landing test:e2e   # Playwright against `vite preview` on :4173
pnpm --filter landing lint
```

`LANDING_API_URL` repoints the dev and preview proxy (default `http://localhost:8000`).

## The pages

| Page | Served at | What it is |
|---|---|---|
| `src/orbiters.html` | `joinorbiters.com/` | The community page and its signup form |
| `src/index.html` | `/pigrocrm` | PigroCRM's own page |
| `src/privacy.html` | `/privacy` | Privacy notice |
| `src/termini.html` | `/termini` | Terms |

The Orbiters form posts to `POST /api/orbiters/signups`, which is implemented in
PigroCRM's API (`projects/pigrocrm/apps/api`) and reached on the same origin. That
endpoint is the one thing this project does not own, and it is why the dev server
proxies `/api`.

## Colour, typeface and the mark

All three come from [`shared/brand`](../../shared/brand), and none of them may be
restated here:

- **Palette.** `src/palette-plugin.ts` reads the seven shared tokens out of
  `@orbiters/brand/palette.css` at build time and prepends them to the two stylesheets
  as plain custom properties. The application consumes the same file as part of its
  Tailwind theme. A hex pasted into a stylesheet here is the fork both mechanisms exist
  to prevent, and the plugin fails the build if the palette stops being extractable.
- **Typeface.** Outfit, self-hosted, declared once in `@orbiters/brand/font.css` and
  prepended the same way. Nothing is fetched from a CDN, on purpose: PigroCRM is sold
  on self-hosting, and a webfont request hands every visitor's IP to a third party.
- **The mark.** The four tiles are `.glyph` in `src/system.css` here and Tailwind
  classes in the application's `BrandMark.tsx`. Both assert their order against
  `@orbiters/brand/mark`, so the two cannot drift.

## How it is served

Today the built output is copied into PigroCRM's web image and served at that origin's
document root, which is why one certificate and one deploy cover both. That is a
serving arrangement rather than a source dependency, and it is transitional: the
community site is not the CRM's. ORB-13 covers giving this project its own image and
its own vhost, which moves two live domains and is therefore a deliberate step.
