# Before and after screenshots on pull requests

Every pull request that changes something a person could see ends with a **before and
after** image in its body. One "after" shot is not enough: only the pair shows what
moved, and the point is that a reviewer sees the difference without checking out the
branch and without reading the diff to reconstruct what the page used to look like.

The `pr-creation` skill (`.claude/skills/pr-creation/SKILL.md`) asks for the section;
this file is how the picture gets made in this monorepo.

## What counts as a visible change

Broader than "frontend files changed". If a reviewer could spot it on screen, it needs a
pair:

- A copy change, including one word of a label, a toast or an empty state.
- A button that appears, disappears, becomes disabled or gains a tooltip.
- A new status pill, badge, column or pane.
- Anything that changes spacing, ordering, or what a menu or a wizard step offers.
- A page of the public site or of the hub, at the viewport it was designed for.

If a pair genuinely cannot be captured, the Screenshots section stays and says why.
Deleting it reads as forgetting.

## Capturing the pair

Both frames: the same page, the same data, the same viewport. The only difference is
which code runs.

**Take the "before" from a second worktree on the base branch.** Never swap files in
place: `git checkout origin/main -- path` overwrites your index and working tree with no
recovery copy, and the restore brings back the last commit rather than what you had in
progress.

```bash
git fetch origin
git worktree add ../<repo>-before origin/main
cd ../<repo>-before && uv sync --frozen && pnpm install --frozen-lockfile --prefer-offline
```

Then run the app you changed from that worktree on a second port, beside your own:

| App | Your worktree | The "before" worktree | Notes |
|---|---|---|---|
| CRM web (`projects/pigrocrm/apps/web`) | `pnpm --filter web dev` on 5173 | `pnpm --filter web dev -- --port 5175` | Both proxy `/api` to the one API on `localhost:8000`, so the data is identical by construction. Start the API once, from either worktree. |
| Hub web (`projects/hub/apps/web`) | `pnpm --filter hub dev` on 5180 | `pnpm --filter hub dev -- --port 5182` | Both proxy `/api` to the hub API on 8084. The page lives under `/hub/`. |
| Website (`projects/website`) | `pnpm --filter website preview` on 4173 | `pnpm --filter website build && pnpm --filter website preview -- --port 4175` | Static: build first, preview serves nginx's path map. |

A page behind the CRM's login needs a session: mint one the way the visual QA does
(`~/pigrocrm-data/tools/mint_session.py` on Ivan's machine) and set the cookie on both
origins, or log in once per origin in the same browser.

Capture with the Playwright MCP: `browser_resize` to the same viewport for both frames
(1440×900 for the CRM and the hub, 390×844 for the website when the change is about a
phone), then `browser_take_screenshot` with a file name that says which frame it is:
`before-invoice-detail.png`, `after-invoice-detail.png`. Set up the fixture you need (an
issued invoice, a draft, a signup) **while you build the change**, not after the PR is
open; the state is cheap to arrange while it is in your head.

Afterwards:

```bash
git worktree remove ../<repo>-before
```

## One image per pair

Compose the two frames side by side, labelled, in one file. `compose.py` beside this
file does it with Pillow, which the repository does not depend on and `uv` fetches on
the spot:

```bash
uv run --no-project --with pillow docs/pr-screenshots/compose.py \
  before-invoice-detail.png after-invoice-detail.png pair-1-invoice-detail.png \
  --box 760,180,640,720
```

`--box x,y,w,h` draws an outline on the after frame around what the change adds, in
source pixels of that frame, in a colour the product's palette does not use, so it reads
as an annotation and not as UI. Measure the box from the after screenshot (Playwright's
`browser_snapshot` with `boxes: true` gives element rectangles); never estimate it. A
guessed box that clips the very text the pair exists to show looks plausible and is
wrong. Crop chrome that is identical in both frames (the sidebar above all) with
`--crop-left <px>` so the content fills the image.

**Open the composite and read it before uploading.**

## Uploading with `gh --attach`

`gh` 2.99.0 or newer (`gh --version`), which is what makes the CLI able to upload a
`user-attachments` image: the only kind a PR body on a private repository renders.
Images committed to the repository, raw links and signed URLs all render broken.

Write the reference in the body first, then attach; `gh` rewrites the reference to the
uploaded URL and keeps your alt text. Without a reference the image is appended at the
end, which is not where a numbered pair belongs.

```bash
# body.md holds, in the Screenshots section:
#   **1. Invoice detail, the PDF pane on the right**
#   ![Invoice detail, before and after](./pair-1-invoice-detail.png)
gh pr edit <n> --body-file body.md --attach ./pair-1-invoice-detail.png
```

`--attach` repeats for several pairs and works on `gh pr create`, `gh pr edit` and
`gh pr comment`. It does not combine with `--web`, and uploads stop at the first
failure with a non-zero exit while the earlier files stay attached: read the exit code.

## Verify before calling it done

```bash
body=$(gh pr view <n> --json body --jq .body)
grep -o user-attachments <<<"$body" | wc -l || true     # must equal the pairs attached
if grep -o '](\./[^)]*)' <<<"$body"; then
  echo "ERROR: the paths above never got rewritten." >&2; false
else
  echo "OK: no local path remains."
fi
```

Then open the PR in a browser and look: a broken attachment still passes a text check.
The images live **in the PR body**. A Linear comment may carry them too, and a list of
local paths handed to the reviewer is never the substitute.
