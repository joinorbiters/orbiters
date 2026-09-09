# The tracker

Linear is where the work is recorded, and using it is not optional. An agent that fixes
something real and leaves no trace has done half the job: the next person, human or
agent, starts from the board, and what is not there did not happen. Linear is the only
tracker for this repository: GitHub issues and any GitHub Project on other repositories
are not part of this repo's flow.

## Where things are

| | |
|---|---|
| Workspace | `joinorbiters` |
| Team | **Orbiters**, issue prefix `ORB-`. One team, and that does not change |
| Initiative | a product, permanent: `Website`, `Hub`, `PigroCRM`, `Monorepo` |
| Project | a release, or a body of work with an end. It closes when it ships, which is what lets its issues archive |
| Milestone | a coherent outcome inside a project's release, not an issue. Costs nothing, shows progress on its own |
| Issue | one agent run, one PR, one worktree |
| Priority | Linear's own field: Urgent, High, Medium, Low. Never a label |
| Effort | Linear's own estimate field. Never a label |
| Statuses | `Backlog`, `Todo`, `In Progress`, `In Review`, `Done`, `Canceled` |
| Type labels | group **type**, exactly one, Linear enforces it because it is a group: `feature`, `fix`, `refactor`, `test`, `chore`, `ci`, `docs`, `design`, `security`, `spike` |
| Area labels | group **Area**, exactly one, Linear enforces it because it is a group: `area:api`, `area:brand`, `area:ci`, `area:core`, `area:infra`, `area:mcp`, `area:repo`, `area:web`, `area:website` |
| Other flat labels | `flagship` for headline work, `parallel` for an issue a parallel agent can take without colliding |

The two lists above are the board's, checked against `list_issue_labels` with
`includeGroups: true` on 2026-09-09, and the board is the authority: an earlier version of
this page named `Bug` and `core`, and an issue filed with those names failed with "Could
not find labels" (ORB-33). Five of the type labels carry a description on the board, and
it is the one to apply: `fix` is something that does not do what it says it does;
`feature` is new behaviour a user or an agent can observe; `refactor` is existing behaviour
made better with no new capability; `chore` is maintenance with no change in behaviour;
`docs` is documentation that stands on its own. `test`, `ci`, `design`, `security` and
`spike` mean what their names say.

The four current projects, each with a lead and both of us as members:

- `Website v1 - the public site, live and correct on a phone`. Lead: Lorenzo.
- `Hub v0 - signups and the company flow, deployed`. Lead: Ivan.
- `PigroCRM v1 - first deploy from CI, with green gates`. Lead: Ivan.
- `Monorepo hygiene v1 - CI cost, licence and the English rule`. Lead: Lorenzo.

Every project always carries a lead and both members, Lorenzo and Ivan, no matter who
leads it. A project created without a lead and without both members is incomplete.

This replaces the old rule that gave every monorepo project (`projects/pigrocrm`,
`projects/website`) its own permanent Linear project. Initiatives are the permanent
containers now, one per product, and a project is scoped work with an end inside one:
an issue in a project that never closes never archives, which is why a project needs a
scope it can actually reach rather than a standing label for a whole product.

Area labels stay a group, so exactly one per issue, and Linear enforces it. I tried to make
them flat on 2026-09-09, because in a monorepo a change genuinely spans two surfaces and
forcing one area drops the other from every area query. It does not work: **a label cannot
be taken out of a group from the MCP surface.** `save_issue_label` with `parent: null`
answers success and echoes `parent` unchanged, and the only thing the UI offers on a group
is Delete, which would take the children with it and they are already applied to every
issue here. So the rule that survives is the old one, and it has a useful side effect: an
issue that genuinely spans two areas is usually two issues, or belongs to the area that
owns the fix. Note that the personal workspace does differ here, where the area labels were
created flat from the start.

## Reaching it

Two skills in `.claude/skills/` carry this contract to the moment it is needed:
`linear-ticket` (the calls, in order, with every field) and `linear-content` (how the
words are written). This file stays the source; a disagreement between it and a skill is
a bug in the skill.


The MCP server is `linear-orbiters`, enrolled per client outside this repository. It is
the only Linear surface you should be using: no other server, and no browser session,
reaches this team's board on Lorenzo's behalf.

Before your first write in a session, make one read call (`list_projects` or
`list_issues`) and check the team name that comes back. Two Linear workspaces are
enrolled on this machine and the failure mode of picking the wrong one is filing a
client's work in the wrong company's board.

## The loop

**Before starting work.** Search the board for the thing you are about to do. If an
issue exists, use it. If it does not, and the work will outlive this run, file one
before you start rather than after: an issue written afterwards is a summary, and it
loses the reasons.

**When you start.** Move it to `In Progress`. If you are working on somebody's behalf,
assign it to yourself so two agents do not pick up the same card.

**While you work.** A comment when you learn something that changes the issue: a
reproduction, a measurement, a cause that turned out to be different from the title, a
decision that is now Lorenzo's. Comments are cheap and they are what makes an issue
readable in a month.

**When your PR is open.** Move the issue to `In Review`, the status for an issue whose
PR is open on GitHub. Until the GitHub integration is approved on this org (see
Commits and issues below), nothing moves it there for you, so do this by hand when you
open the PR.

**When you finish.** `Done` means verified on the surface the issue is about, and the
comment that closes it says how. A green CI check closes a CI issue. A deploy issue
closes when the deploy has run and a request that exercises the new code came back
right, never on a 200 from an unchanged path. If you cannot verify it, say so and leave
it open.

**Project updates.** Post one whenever something happened that a reader could not infer
from the issue list: a milestone slipped, a health change (`onTrack`, `atRisk`,
`offTrack`), a decision taken, a release shipped. `save_status_update` requires
`type: "project"` along with the project, so a call without it fails validation. An
update that only restates the board is noise, but skipping one when the board alone
would mislead a reader is worse.

## What an issue carries

- A **title that states the observed problem**, not the intended fix: "the backend gate
  installs neither pandoc nor typst" rather than "add pandoc to CI". The fix is often
  not the one you first thought of, and a title written as a fix ages into a lie.
- **Project**, its **milestone** (unless the issue genuinely belongs to no body of
  work), one **area:\*** label, one **type** label, a **priority**, and an
  **estimate**. `save_issue` takes all of this in the same call, so an issue that is
  missing one of them is a mistake, not the accident of a skipped second call.
- A body with the evidence: what was observed, where (path and line, or the run URL),
  what it blocks, and what it needs. Point at a spec rather than copying it, since the
  copy will drift.
- What you deliberately did **not** do, when there is such a thing. An issue that hides
  a decision costs a whole round trip later.

## Rules

- **File what you find.** A defect you noticed and did not fix goes on the board before
  you finish, with the evidence you already have in your hands. This is the single rule
  that decays fastest under time pressure and the one worth most.
- **Do not silently fix somebody else's defect** in an unrelated change. File it, and
  say in your own commit that you left it alone. Choosing the fix is often a design call
  that belongs to whoever owns that code.
- **Do not close what you did not verify**, and do not move a card on somebody's promise
  that it works.
- **One area per issue**, because both label families are groups and Linear allows only
  one label from a group. An issue that genuinely spans two areas is usually two issues,
  or belongs to the area that owns the fix. Do not spend a call trying to apply two: the
  second is silently dropped.
- **Never invent an issue id.** If you reference `ORB-N` in a commit, a comment or a
  document, it exists and you have read it.
- **The tracker is not documentation.** A design rule goes in `docs/design/DECISIONS.md`,
  a procedure goes in `AGENTS.md` or a project README, and an issue points at them. Work
  that is finished and needs no decision is recorded by its commit, not by a `Done` issue
  filed for the sake of having one.
- **English, first person, no em dashes**, same as every other repo-facing surface. See
  the Conventions section of the root `AGENTS.md`.

## Commits and issues

Linear's GitHub app (`linear-code`) is connected on Lorenzo's personal workspace. On
`joinorbiters` the install is requested and pending: Lorenzo is a member of the org, not
an owner, and only the org owner (`slavni96`) can approve it. Until it is approved,
nothing closes itself here. Reference the issue in the commit body when the commit is
the work (`ORB-9 covers the real fix`), treat that reference as a pointer only, and
change the state yourself with the evidence in a comment.

Once approved, a branch named from the issue links its PR automatically, and moving an
issue to `In Review` becomes something the PR does on its own rather than a manual step.

## API details worth knowing before you waste a call

- `save_comment` takes `issueId`, not `issue`.
- `save_issue` accepts `state`, but `get_issue` echoes it back under `status`.
- `milestone` is accepted on write and not echoed: verify through `list_milestones` and
  its `progress`.
- Label names are case-insensitive across the whole workspace, and retiring a label
  does not free its name. Creating a lowercase label that collides with an old
  capitalised one (`Bug` versus `bug`, say) silently resolves onto the old, retired
  label instead of creating a new one. If that happens, fix it by reusing the colliding
  label: update it by id with the new name and the right parent, do not try to create
  a second one.
- Initiatives cannot be created from the MCP surface at all. `save_project` can attach
  an existing initiative with `addInitiatives`, but there is no `save_initiative`.
  Initiatives are created by hand in the Linear UI; automation only creates projects and
  issues underneath them.
