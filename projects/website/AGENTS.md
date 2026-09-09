# website: what to know before changing it

joinorbiters.com. Read `README.md` here first for what the pages are and how to run
them; this file is the part that is easy to get wrong.

Tracker: the **Website** project in Linear, conventions in `docs/tracker.md` at the
repository root. Everything in the repository is written in English, product copy
excepted: these pages speak Italian to their visitors and that is what they should keep
doing.

## No framework, and that is the requirement

No React, no Tailwind, no router, no CSS framework. Four HTML pages, three scripts,
three stylesheets, and a build that takes about 300 milliseconds. This is the first
thing a visitor loads and it must not drag an application bundle behind it. A dependency
added here has to justify itself against that, and "the CRM already uses it" is not a
justification: the CRM is behind a login and this is not.

## Colour, typeface and the mark come from `shared/brand`

Never restate them. `src/palette-plugin.ts` reads the shared tokens out of
`@orbiters/brand/palette.css` at build time and prepends them to the stylesheets; the
CRM consumes the same file through its Tailwind theme. A hex typed into a stylesheet
here is the fork both mechanisms exist to prevent, and the plugin fails the build when
the palette stops being extractable rather than shipping pages with no colour.

The token count in `EXPECTED_TOKEN_COUNT` is asserted deliberately: adding a token to
the shared palette without deciding whether these pages need it is a failing test, not a
silently thinner site.

## The page names still say "landing", on purpose

`src/landing.css`, `src/landing.js` and the three `landing-*.test.ts` files are named
after the landing page, `index.html`, which is PigroCRM's own page and shares its
stylesheet with `/privacy` and `/termini`. The **project** was renamed from `landing` to
`website` on 2026-09-09 because it is the whole site; the page inside it did not go
anywhere. `src/orbiters.*` is the community page and stands apart.

## What this project does not own

`POST /api/orbiters/signups` is PigroCRM's, implemented in `projects/pigrocrm/apps/api`
and reached on the same origin. The dev and preview servers proxy `/api` for that reason
alone; `WEBSITE_API_URL` repoints it.

Serving is also not owned here yet: the built output is copied into the CRM's web image
and served at the document root. That is transitional and ORB-12 carries it. Until then,
a change to how these pages are served is a change to
`projects/pigrocrm/Dockerfile.web` and `projects/pigrocrm/deploy/nginx/`, and it needs
the CRM's image rebuilt to be seen.

## Verification

`pnpm --filter website lint | test | build | test:e2e`, all fast. The e2e suite runs
Playwright against `vite preview` on the fixed port 4173, which is why its preflight
check is `serial: true`. A change to the rendered pages is not done until you have run
it, and a visual claim needs a render, not a description.
