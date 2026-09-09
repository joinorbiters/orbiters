# The tracker

Linear is where the work is recorded, and using it is not optional. An agent that fixes
something real and leaves no trace has done half the job: the next person, human or
agent, starts from the board, and what is not there did not happen.

## Where things are

| | |
|---|---|
| Workspace | `joinorbiters` |
| Team | **Orbiters**, issue prefix `ORB-` |
| Projects | one per monorepo project: **PigroCRM** (`projects/pigrocrm`), **Website** (`projects/website`) |
| Priority | Linear's own field: Urgent, High, Medium, Low. Never a label |
| Type labels | `Bug`, `Feature`, `Improvement`, `Chore`, `Docs`. Exactly one |
| Area labels | group **Area**: `api`, `web`, `mcp`, `core`, `infra`, `ci`, `website`, `brand`, `repo`. Exactly one |
| Milestones | belong to a project, and only where the project has outcomes that can finish |

A new monorepo project opens its own Linear project. Never a shared one, and never a
label standing in for a project: `docs/adding-a-project.md` §9.

## Reaching it

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

**When you finish.** `Done` means verified on the surface the issue is about, and the
comment that closes it says how. A green CI check closes a CI issue. A deploy issue
closes when the deploy has run and a request that exercises the new code came back
right, never on a 200 from an unchanged path. If you cannot verify it, say so and leave
it open.

## What an issue carries

- A **title that states the observed problem**, not the intended fix: "the backend gate
  installs neither pandoc nor typst" rather than "add pandoc to CI". The fix is often
  not the one you first thought of, and a title written as a fix ages into a lie.
- **Project**, one **Area** label, one **type** label, a **priority**, and a milestone
  when the project has them.
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
- **One Area per issue.** Linear enforces it, and it is a useful pressure: an issue that
  genuinely spans two areas is usually two issues, or is filed against the area that
  owns the fix.
- **Never invent an issue id.** If you reference `ORB-N` in a commit, a comment or a
  document, it exists and you have read it.
- **The tracker is not documentation.** A design rule goes in `docs/design/DECISIONS.md`,
  a procedure goes in `AGENTS.md` or a project README, and an issue points at them. Work
  that is finished and needs no decision is recorded by its commit, not by a `Done` issue
  filed for the sake of having one.
- **English, first person, no em dashes**, same as every other repo-facing surface. See
  the Conventions section of the root `AGENTS.md`.

## Commits and issues

There is no Linear/GitHub integration on this repository, so nothing closes itself.
Reference the issue in the commit body when the commit is the work (`ORB-9 covers the
real fix`), and change the state yourself with the evidence in a comment.

## API details worth knowing before you waste a call

- `save_comment` takes `issueId`, not `issue`.
- `save_issue` accepts `state`, but `get_issue` echoes it back under `status`.
- `milestone` is accepted on write and not echoed: verify through `list_milestones` and
  its `progress`.
- Labels in the **Area** group are workspace-level. Creating one with a `teamId` fails
  with "Cannot add a label to a group from a different team": pass the group's id as
  `parent` and no team.
- `list_issue_labels` hides groups unless you pass `includeGroups: true`, which is how
  you get the Area group's id.
