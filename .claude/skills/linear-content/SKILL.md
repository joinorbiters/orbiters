---
name: linear-content
description: Use when writing anything that lands on Linear for this repository: an issue title and body, a comment, a closing comment, a project description, a project status update. The shape, the language and what never goes in, with templates, so every card reads the same way. Triggers whenever `save_issue`, `save_comment`, `save_project` or `save_status_update` is about to be called.
---

# Writing on Linear

Everything on the board is written for a reader who opens it in a month with no memory
of the session: a person, or the next agent. That reader needs to know what was
observed, what was decided, where the evidence is, and what was left undone on purpose.

## Language

English, first person, plain words, the way you would say it to a colleague. No em
dashes, no "not just X but Y", no emoji, no selling ("robust", "seamless", "powerful").
Italian only inside «guillemets» when quoting what the product says to its users or what
the person you work for said. Real newlines, never `\n` escapes. Markdown headings are bold lead words, not
`#` titles: a card is not a document.

## The title

States the **observed problem**, as a sentence with a verb, under 100 characters. Never
the intended fix, because the fix changes and a title written as a fix ages into a lie.

- Good: `A draft invoice cannot be deleted from the application, though the API allows it`
- Good: `The invoice page shows the numbers but never the document: the PDF is a download only`
- Bad: `Add delete button to invoice page`
- Bad: `PDF preview`

## The issue body

Five lead words, each a short paragraph or a few bullets. Skip one only when it has
nothing to say, never because it is inconvenient.

```markdown
**Observed.** What happens today, where (`path/to/file.py:123`, a URL, a run id), for
whom, and what it costs. A quote from the person who asked, in «guillemets», with the
date, when the ask is theirs.

**What exists.** The pieces already in place that the fix will use or must respect:
the service, the route, the spec paragraph (`docs/.../spec.md §4`), the test that
already pins the rule. Point at them; do not copy them.

**What is needed.** The outcome, as behaviour a reader can check, not a list of files
to edit. Where a design choice is already taken, say so and where it is recorded.

**Deliberately not done.** What a reader might expect and will not find, with the
reason, so the next person does not reopen a closed question.

**Adjacent.** The open cards next to this one, found as the `linear-ticket` skill
says, and what was done about each: linked, narrowed around, waited for. Or that there
were none: which area calls answered empty, and the Done cards `query` ranked first for
the surface, so a reader can tell the board was read.
```

**Adjacent** is skipped only on a card filed for later, and added when the card is
picked up (`patch` with `op: "append"`, in the call that moves it). Optional, when they
apply: **Evidence** (the reproduction, the measurement, the log line), **Blocks** /
**Blocked by** (issue ids you have read), **Decision for the lead** (the project's lead
per `docs/tracker.md`: one question, the options, your recommendation first).

## Comments

One comment per event that changes the issue. Each opens with a bold lead that says
which kind it is, so a reader can skim the thread.

- **Progress.** `**Step 4 done and live:** ...` What landed, where to see it, the commit.
  Never "working on it".
- **Found.** `**Cause is different from the title:** ...` The reproduction or measurement,
  and what it changes about the plan.
- **Scope.** `**Scope, narrowed:** ...` or `**Scope, grown:** ...` What the card now
  covers that it did not, or no longer covers, and why: a neighbour found late, a file
  that had to move too, a piece left for its own card (with the id, once filed).
- **Waiting.** `**Waiting on Lorenzo:** ...` What you are stopped on, from whom, and what
  you will do when it arrives. One comment when you stop, one when it lifts.
- **Decision.** `**MCP, decided.** ...` What was chosen, the reason, where it is recorded
  (`DECISIONS.md` row, spec paragraph). If it is the lead's to take: the question, the
  options, your recommendation, and stop.
- **PR.** `PR: <url> (branch ...)` plus one sentence on what it contains and what is
  still running (review, CI).
- **Review.** `**Review applied:** ...` How many findings, which changed the code (commit
  sha), which you left as they were and why. The full record stays on the PR; the card
  gets the one line that says the PR is not what it was when it opened. The same shape
  for a CI run that went red (`**CI red:** run ..., <job>, <cause>`, written when you
  see it, with the sha of the fix added to the same comment when you push it).
- **Closing.** `**Merged:** <url> (merge commit ...)` or `**In production:** tag ...`
  followed by `Evidence:` and a bulleted list a reader can chase: run ids with the job
  names that went green, test counts, the request you made and what came back, what you
  opened in a browser and saw. Then `Left open on purpose:` if anything is.

## Project description

For `save_project`: what the project is in one sentence, where it lives in the
repository (`projects/<name>/`), what it is made of (one bullet per package or app, with
the port or URL where it answers), the design record and the orientation file
(`docs/superpowers/specs/...`, `AGENTS.md`), how it deploys (workflow, compose project,
tag pattern). `links` to the code and to the live surface. `summary` under 255 chars,
stating the outcome the project ends with.

## Status updates

`save_status_update` with `type: "project"`. One paragraph a reader who sees only the
update understands: what shipped or slipped, the health word and why, the next
visible thing. Post one when the board alone would mislead; skip it when it would only
restate the issue list.

## References

- Commits: seven-character sha in backticks, `03c4461`. Tags as written, `pigrocrm-v0.1.0`.
- CI: the run id and the job name that matters, `run 34351172643, pigrocrm · web`.
- Code: `path/from/repo/root.py:123`, or the symbol in backticks.
- PRs and pages: the full URL.
- Issues: `ORB-N`, only one you have read.

## What never goes on the board

Secrets, tokens, passwords or where to find them beyond "on the server, root-only".
Personal data of a customer or a signup (a name, an email, a CV). Screenshots with real
customer data. A claim a test did not make. A restated board. A decision that belongs
in `docs/design/DECISIONS.md` and is not also recorded there. An issue filed after the
work only to have a `Done` card: the commit is the record of finished work that needed
no decision.
