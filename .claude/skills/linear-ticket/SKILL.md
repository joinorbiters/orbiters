---
name: linear-ticket
description: Use when filing, finding, moving or closing a Linear issue for this repository (team Orbiters, ORB-N), or posting a project update. The MCP workflow with every field in one call, the state changes at each step, and the API quirks that otherwise cost a wasted call. Triggers on "crea ticket", "apri un'issue", "file this", "move to Done", "update the project".
---

# Working the Linear board

`docs/tracker.md` is the contract: what an issue carries, when it moves, what closes it.
Read it once per session. This skill is the sequence of calls and the traps. Content
(how to write the body, a comment, an update) is the `linear-content` skill.

## First call of the session

One read (`list_projects` or `list_issues` with `team: "Orbiters"`) and check the team
that comes back is **Orbiters** (`ORB-`). Two workspaces are enrolled on this machine;
filing a client's work in the wrong company's board is the failure mode.

## Finding before filing

`list_issues` with `team: "Orbiters"` and `query: "<two or three words of the problem>"`,
then with the `area:*` label. An issue that exists is used, moved and commented; a new
one is filed only when none does, and **before** the work starts, never after.

## Filing: one `save_issue` call

Every field at once; a second call to add the missing ones is the sign the first was
wrong.

| Field | Value |
|---|---|
| `team` | `"Orbiters"` |
| `project` | **the project id**, from `list_projects`. Project names carry a version suffix (`PigroCRM v1 - first deploy from CI, with green gates`) and change; a lookup by the old name fails with "Could not find project". |
| `milestone` | the milestone id from `list_milestones(project)`, unless the issue genuinely belongs to no body of work. It is accepted and not echoed back: trust `list_milestones` progress, not the response. |
| `title` | the observed problem, not the fix: "the invoice page shows the numbers but never the document", not "add a PDF preview". |
| `description` | per the `linear-content` skill. Real newlines, never `\n` escapes. |
| `addLabels` | exactly two: one from the `type` group (`fix`, `feature`, `refactor`, `chore`, `docs`, `test`, `ci`, `design`, `security`, `spike`) and one from `Area` (`area:web`, `area:api`, `area:core`, `area:mcp`, `area:infra`, `area:ci`, `area:website`, `area:brand`, `area:repo`). Both are groups: a second label from the same group is silently dropped. Use `addLabels`, never `labels`: `labels` replaces the whole set. |
| `priority` | 1 Urgent, 2 High, 3 Medium, 4 Low. A field, never a label. |
| `estimate` | the team's points. |
| `assignee` | `"me"` when you are about to work it. |
| `state` | `"In Progress"` when you start now, otherwise leave the default. |

Label names are case-insensitive workspace-wide and a retired label keeps its name:
`Chore` resolves to whatever old label owned that name. Use the exact lowercase names
above; `list_issue_labels` with `includeGroups: true` is the source when in doubt.

## Moving it

- **`In Progress`** when you start, with `assignee: "me"`.
- **`In Review`** when the PR is open. Comment the PR URL. Nothing does this for you
  until the GitHub app is approved on the org.
- **`Done`** only against evidence on the surface the issue is about, in the closing
  comment: the run id and job names that went green, the commit sha, what you opened
  and what came back. A green CI closes a CI issue; a deploy issue closes when a request
  that exercises the new code came back right, never on a 200 from an unchanged path.
  If you cannot verify, say so in a comment and leave it open.
- **`Canceled`** for won't-do, with the reason.

`save_issue` accepts `state`; `get_issue` echoes it as `status`. Both are the same field.

## Commenting

`save_comment` with `issueId` (not `issue`) and `body`. When: something changed the
issue (a reproduction, a measurement, a cause different from the title, a decision that
is now Ivan's), a PR opened, a step of a plan landed, the closing evidence. Not: "working
on it". Replies in a thread take `parentId`.

## Project updates

`save_status_update` with `type: "project"`, the project id, a `health` (`onTrack`,
`atRisk`, `offTrack`) and a body per the `linear-content` skill. Post one when the board
alone would mislead a reader: a release shipped, a milestone slipped, a decision taken.
Not one that restates the issue list.

## References in code and commits

`ORB-N` in a commit body or a comment is a pointer to an issue you have read. Never
invent one. The branch is the issue's `gitBranchName`, taken from the `save_issue` or
`get_issue` response, not typed by hand.

## What the tracker is not

Documentation. A rule goes to `docs/design/DECISIONS.md`, a procedure to `AGENTS.md`,
and the issue points at them. Work that needs no decision is recorded by its commit,
not by a `Done` card filed for the sake of having one.
