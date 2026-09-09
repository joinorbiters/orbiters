---
name: pr-creation
description: Use when opening, describing or merging a pull request in this monorepo. Enforces the branch, the Conventional Commit title, the body in the repository's own template sections, the review and merge loop, and the hand-off to Linear. Triggers on "open a PR", "submit for review", "review and merge", or the Italian «apri una PR», «fai review e mergia».
---

# Opening a pull request here

The contract lives in three files this skill points at and restates as little as it
can: the root `AGENTS.md` (Conventional Commits, English, no trailers, release only
through CI), `.github/PULL_REQUEST_TEMPLATE.md` (the body's sections) and
`docs/tracker.md` (what Linear needs at each step). This skill is the order of
operations and the shape of each piece, so two agents open the same kind of PR. Where
it and a document disagree, the document is right and the skill has a bug.

## Before the branch exists

1. **A Linear issue exists and is `In Progress`.** Find it with `list_issues` or file it
   with the `linear-ticket` skill. No issue, no branch: the issue is where the reasons
   live, and a PR written first loses them.
2. **The branch is Linear's.** Use the issue's `gitBranchName` (`ivansala/orb-42-...`),
   in a git worktree of its own, never on `main` and never in the shared checkout:

   ```bash
   git fetch origin
   git worktree add -b <gitBranchName> ../<repo>-orb<N> origin/main
   cd ../<repo>-orb<N>
   uv sync --frozen && pnpm install --frozen-lockfile --prefer-offline
   ```

   Other sessions write to the same index; a worktree is what keeps your commit yours.
3. **Read the project's `AGENTS.md`** (`projects/<name>/AGENTS.md`) before its source.

## Commits

As the root `AGENTS.md` Conventions say (Conventional Commits, English, first person,
no AI trailer). What that section does not say: the subject states what is true after
the commit (`feat(web): a draft invoice can be deleted from its page`), the body says
why and what was deliberately left alone, the last line is the issue (`ORB-42.`), you
commit with a pathspec (`git add <files>`, never `-A`, other sessions share the index),
and a migration or a file move gets a commit of its own.

## Title

The PR title is the subject of the commit that is the work, under 72 characters:

```
type(scope): what is true now
```

`type` is one of `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `ci`, `chore`,
`style`, `revert`. `scope` is the project or the app: `web`, `api`, `core`, `mcp`
(the CRM), `hub`, `website`, `brand`, `ci`, `repo`. After the colon the first word is
lowercase and nothing is in Title Case; a verb in the present: what the reader gets, not
what you did to the files.

## Body

The template's three sections, in the first person and in its order. Conditional
sections go after «How I verified it» and before «Anything a reviewer should look at
twice»; the Linear line closes the body. `gh pr create --body-file -` with a heredoc.

```markdown
## What this changes

<The first sentence names the problem: what was wrong, missing or impossible before.
Then what is true now, in words a product person understands. Bullets or a paragraph,
whichever reads better. Example strings, numbers and states beat descriptions of them.>

## How I verified it

<The commands and what they said: test counts, the gate names that went green, the
URL you opened and what you saw. Never "tests pass". If something could not be
verified, which part and why.>

## Anything a reviewer should look at twice

<The bit you are least sure about, a decision that could have gone the other way, a
path no test covers. Delete this section if there is genuinely nothing.>
```

Conditional sections, each only when true (paths from the repository root; the CRM is
`projects/pigrocrm`, the hub `projects/hub`):

- **`## What did not change, on purpose`** when a reviewer could reasonably assume a
  neighbouring thing moved (an MCP tool that deliberately does not follow a new button,
  a list that does not get the new action). Say it, and say where the decision is
  recorded (the Linear issue, `docs/design/DECISIONS.md`).
- **`## Migrations`** when `projects/*/packages/core/migrations/versions/` changed: the
  revision, what it creates or alters in plain words, whether it is safe on a table that
  already exists in production (`IF NOT EXISTS` where the table was adopted), and what
  `compare_metadata` in the migration test says.
- **`## API changes`** when a FastAPI route, request or response shape changed: the
  `METHOD /path`, the fields that changed, the status codes. For the CRM, that
  `pnpm --filter web generate:api` was run with the API up on `localhost:8000`, so
  `projects/pigrocrm/apps/web/src/lib/api-types.ts` matches (the web reads the generated
  types, never hand-written ones). The hub's web has a hand-written client in
  `projects/hub/apps/web/src/lib/api.ts`: say what changed there.
- **`## MCP surface`** when a tool was added, removed or renamed. For the CRM
  (`projects/pigrocrm/apps/mcp`): which service method backs it, and what changed in
  `tests/test_mcp_surface_coverage.py` and `tests/test_mcp_invoice_ban.py`, the record
  of what an agent may and may not do. For the hub (`projects/hub/apps/mcp`): the
  change to `tests/test_tools.py`.
- **`## Screenshots`** for anything a person could see: a label, a pill, a disabled
  button, a new pane, a reordered menu. A **before and after pair**, composed into one
  side-by-side image per pair, taken on the same data at the same viewport. Never
  committed: attach with `gh pr edit <n> --attach ./pair-1.png` (the flag exists from
  `gh` 2.99.0; check `gh --version`). If a pair cannot be captured (no fixture, no running stack),
  keep the section and say why. Deleting it reads as forgetting.

The last line of the body: `Linear: ORB-N.`

## After `gh pr create`

1. Move the issue to **`In Review`** and comment the PR URL on it (the GitHub app is not
   approved on this org yet, so nothing does this for you).
2. **Independent review.** Dispatch a fresh, read-only reviewer (an `Agent` of type
   `general-purpose`, told the worktree path, the diff command, the files that give it
   context, and to rank findings by severity with a concrete fix each). Do not review your
   own diff and call it a review.
3. **Apply the findings in a second commit**, push, and record the review on the PR as
   a comment: each finding, what you did with it, and what you left as is and why.
4. **Wait for CI**: `gh pr checks <n> --watch`. The `ci` job is the only status that
   matters; the others may skip by path filter.
5. **Merge with a merge commit**, the repository's shape:
   `gh pr merge <n> --merge --delete-branch`. Never squash a two-commit PR whose second
   commit is the review: the history is the record.
6. **Clean up**: `git worktree remove ../<repo>-orb<N>`, `git worktree prune`.
7. **Close on Linear only with evidence**: run ids, commit sha, the test counts, what
   you opened and saw. Preview deploys on the green trunk run; **production moves only
   on a tag** (`docs/design/DECISIONS.md`, 2026-09-09) and only when asked.

## What never goes in a PR

Secrets, tokens, passwords, personal data of a customer, screenshots of real customer
data, an issue id you did not read, a claim a test did not make, an AI trailer.
