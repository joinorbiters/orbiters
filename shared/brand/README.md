# @orbiters/brand

The palette, the typeface and the four-tile mark. One source, no copies, read by every
Orbiters surface.

| File | What it holds | Who reads it |
|---|---|---|
| `palette.css` | Six colours and `--font-sans`, in a Tailwind `@theme` block | The CRM's `tokens.css` imports it; the website extracts it at build time |
| `font.css` + `fonts/` | Outfit, self-hosted, one variable file for the 300-700 range | Both surfaces |
| `mark.ts` | The order of the four tiles, and how each surface names them | Both surfaces' tests |

## Why a package rather than a file in one of the projects

The CRM is built with Tailwind and the website deliberately has none, so they cannot
share a stylesheet: the application consumes `@theme` and generates utilities from it,
while the website reads the same declarations as text and injects them as plain custom
properties. What they must share is the *values*. Keeping those in either project would
make one of them depend on the other, and keeping a copy in each is the drift this
package exists to prevent.

## What is deliberately not here

`--radius`. The website's visual system is square by design: tiles, hard edges and a
stepped shadow, with no rounded corner anywhere. The radius scale is the application's
own and lives in its `tokens.css`. It used to arrive here by accident, along with the
26 semantic re-exports of `@theme inline`, back when the website extracted them out of
the application's own stylesheet and used none of them.

## Changing a colour

Edit `palette.css`. Both surfaces pick it up from the same declaration, and three test
suites will tell you if something drifted: the application's `tokens.test.ts` checks
contrast ratios against the values, the website's `landing-tokens.test.ts` checks that
no stylesheet restates them, and `palette-plugin.test.ts` asserts the exact set of
seven tokens the website receives.
