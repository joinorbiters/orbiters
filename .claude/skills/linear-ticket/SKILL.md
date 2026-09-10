---
name: linear-ticket
description: Use when filing, finding, moving or closing a Linear issue for this repository (team Orbiters, ORB-N), or posting a project update. The MCP workflow with every field in one call, the state changes at each step, and the API quirks that otherwise cost a wasted call. Triggers on "file this", "move to Done", "update the project", or the Italian «crea ticket», «apri un'issue».
---

# Working the Linear board

`docs/tracker.md` is the contract: what an issue carries, when it moves, what closes it.
Read it once per session. This skill is the sequence of calls and the traps. Content
(how to write the body, a comment, an update) is the `linear-content` skill.

## First call of the session

The MCP server is `linear-orbiters`, the only Linear surface for this board. Two reads
before any write. `list_projects` or `list_issues` with `team: "Orbiters"`, and check the
team that comes back is **Orbiters** (`ORB-`): two workspaces are enrolled on this
machine, and filing a client's work in the wrong company's board is the failure mode.
Then `get_user` with `query: "me"`, and keep the `id` it returns, not the display name:
it is the account this session writes as, it is what `assignee: "me"` will mean, it is
what every ownership test below compares against, and it is not necessarily the person
talking to you. Both people on this team run agents against the same board.

## Finding before filing, and whether it is yours to take

`list_issues` with `team: "Orbiters"` and `query: "<two or three words of the problem>"`,
then with the `area:*` label. Ask for `assigneeId`, `createdById`, `statusType` and
`labels` in `fields`, because an issue that exists is not an issue that is available
(`docs/tracker.md` § Who owns a card). Compare ids against the `id` you kept from
`get_user`, never display names:

- `assigneeId` is you: yours, use it, move it, comment on it.
- `assigneeId` is somebody else, or `statusType` is `started` under their name: theirs.
  Leave every field alone, add a comment only if you have something useful, and pick
  other work. Never `assignee: "me"` on it, not even when you are about to fix exactly
  that, and not because the person talking to you asked for it by id: if it is theirs,
  they reassign it and you proceed.
- no `assigneeId`: it belongs to whoever filed it (`createdById`).
- labelled `parallel`, with no `assigneeId` and not `started`: whoever is free may take
  it, whoever filed it. The label opens an unclaimed card; it never reopens a claimed
  one.

Looking for something to work on rather than checking one card: `list_issues` with
`assignee: "me"`, which does filter, and `label: "parallel"`, which does not filter on
ownership at all, so drop from it every row carrying an `assigneeId` that is not yours or
a `statusType` of `started`. The unassigned list is not filterable either:
`assignee: null` and `assignee: "null"` are both accepted and both silently ignored, so
the response still carries everybody's cards (measured 2026-09-09, against the tool's own
description). Narrow it server-side (`state: "Todo"`, then `state: "Backlog"`), raise
`limit` past the default 50, and filter the rows yourself. Those lists together are the
work you may start.

A new issue is filed only when none exists and the work will outlive this run, and then
**before** the work starts, never after (`docs/tracker.md`, The loop).

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
| `assignee` | never omitted. `"me"` when you will do the work, the person who asked for it when they will. A card filed for later still gets one: an empty assignee reads as free to the other agent. |
| `state` | `"In Progress"` when you start now, otherwise leave the default. |

Label names are case-insensitive workspace-wide and a retired label keeps its name:
`Chore` resolves to whatever old label owned that name. Use the exact lowercase names
above; `list_issue_labels` with `includeGroups: true` is the source when in doubt.

## Moving it

When each state applies, and what closes an issue, is `docs/tracker.md` § The loop; do
not learn it from here. What that section leaves to the caller:

- `In Progress` goes with `assignee: "me"` in the same call, and only on a card that is
  already yours (§ Finding before filing). On somebody else's card both fields stay as
  they are.
- `In Review` is set by you when the PR opens, with a comment carrying the PR URL. The
  PR links itself to the issue, so seeing the link is not seeing a state change: the
  status automation is a per-team setting and it is off here (PR #33 linked, ORB-80
  stayed `In Progress`). Move it yourself.
- `Done` takes a closing comment shaped as the `linear-content` skill says (`Evidence:`
  with run ids, sha, what you exercised and what came back). No evidence, no `Done`.
- Won't-do is `Canceled` (one `l`), with the reason.

`save_issue` accepts `state`; `get_issue` echoes it as `status`. Same field.

`save_issue` overwrites `assignee` with whatever you send, with no compare-and-set and
nothing in the response to say whose card it was a second earlier, and the field keeps no
history you can read back. Reading the owner first is the only guard.

## Commenting

`save_comment` with `issueId` (not `issue`) and `body`. When: something changed the
issue (a reproduction, a measurement, a cause different from the title, a decision that
is now the project lead's), a PR opened, a step of a plan landed, the closing evidence.
Not: "working on it". Replies in a thread take `parentId`.

## Project updates

`save_status_update` with `type: "project"`, the project id in a key called **`project`**,
a `health` (`onTrack`, `atRisk`, `offTrack`) and a body per the `linear-content` skill.
Both of those are easy to get wrong once: omitting `type` fails on `type: is required`,
and passing the id as `projectId` fails on `project is required when creating a project
status update` while the id is right there in the payload. Post one when the board alone
would mislead a reader: a release shipped, a milestone slipped, a decision taken. Not one
that restates the issue list.

## References in code and commits

`ORB-N` in a commit body or a comment is a pointer to an issue you have read. Never
invent one. The branch is the issue's `gitBranchName`, read from `get_issue` (or
`list_issues` with `fields: ["gitBranchName"]`), not typed by hand.

That name is rendered for **whoever asked for it**, not for the assignee: the same card
answers `fiorelorenzo/orb-41-...` to one of us and `mariorossi/orb-41-...` to the other. So
it is the branch to use once the card is yours, and it is never evidence that it is.

## What the tracker is not

Documentation: `docs/tracker.md` § Rules says where a rule, a procedure and finished
work go instead. An issue points at those places.
