# Does Gmail preserve a client-supplied Message-ID on messages.send?

**Status:** UNVERIFIED
**Recorded:** 2026-08-30 · **By:** agent, task B2-1 · **Account type:** none — no live account was used

> **No live verification has been performed.** Everything below the "Method" heading is
> either a description of the check still to run or documentary evidence about it. The
> `YES` branch is currently *assumed*, not established, and `FakeGmail` encodes that
> assumption. This paragraph exists so nobody downstream can mistake the record for a
> result.

## Method (the check that settles it)

Send an RFC822 message carrying `Message-ID: <pigrocrm-verify-…@example.invalid>` through
`POST /gmail/v1/users/me/messages/send`, then query
`users.messages.list?q=rfc822msgid:<the same id>`. One message back means the header was
preserved and the exact path of spec 6.3 holds; zero means Gmail replaced it.

```bash
# An access token with gmail.send + gmail.readonly, from a throwaway Google account
# through the app's own /api/gmail/oauth/start on a dev instance.
MSGID="pigrocrm-verify-$(date +%s)@example.invalid"
RAW=$(printf 'From: me@example.it\r\nTo: me@example.it\r\nSubject: verifica Message-ID\r\nMessage-ID: <%s>\r\nContent-Type: text/plain; charset="UTF-8"\r\nContent-Transfer-Encoding: quoted-printable\r\n\r\nverifica\r\n' "$MSGID" \
  | base64 | tr '+/' '-_' | tr -d '=\n')
curl -sS -X POST "https://gmail.googleapis.com/gmail/v1/users/me/messages/send" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"raw\":\"$RAW\"}"
curl -sS -G "https://gmail.googleapis.com/gmail/v1/users/me/messages" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  --data-urlencode "q=rfc822msgid:$MSGID"
```

## Why it has not been run

The check is a live call to Google, and this repository's root `conftest.py` refuses any
socket to anything but loopback — deliberately, so that no part of the suite can quietly
depend on the network. The agent implementing B2-1 has no Google account, no OAuth client
and no dev instance, and disabling the guard to obtain one would trade a permanent
property of the suite for a single fact. So the fact is left explicitly unestablished
rather than manufactured.

**This is the one step of plan 5B-2 that a human has to perform.** It takes about five
minutes with a throwaway account.

## Result

- Message-ID preserved: **UNVERIFIED**
- Messages returned by the rfc822msgid query: **not run**
- The id Gmail assigned: *not run*

### Documentary evidence, which is not a substitute

Google documents the `rfc822msgid:` search operator, and documents `messages.send` as
sending "the specified message" — neither statement says whether the `Message-ID` header
of that message survives. Two web searches (2026-08-30) over Google's own Gmail API
reference turned up no statement either way; what they did turn up is that mail service
providers *in general* commonly rewrite `Message-ID` so the right-hand side names their
own infrastructure, which is a reason to expect `NO` for some providers and says nothing
certain about Gmail's own API path. Inconclusive, and recorded here only so the next
person does not repeat the search believing it was never done.

## Consequence

- **YES** → `PIGROCRM_GMAIL_RECONCILE_BY_MESSAGE_ID` stays `true`. Reconciliation is
  exact: one lookup, one answer, no guessing. This is the path spec 6.3 wants.
- **NO** → set it to `false`, and change `FakeGmail._register_sent` to mint its own
  `Message-ID` instead of keeping ours, because every test built on the fake is otherwise
  testing a contract Gmail does not offer. Reconciliation falls back to matching on
  recipient + subject + `internalDate` inside the grace window, within the per-address
  sweep the sync already performs. This is **declaredly inferior** — it is an approximate
  match, and two identical messages minutes apart are indistinguishable under it — which
  is exactly why the Message-ID path is the one to use if it holds.
- **UNVERIFIED** (today) → the setting keeps its `true` default because the exact path is
  the one the design is built around and the fallback is worse, but that default is an
  *assumption about a third party*, not a measurement. If reconciliation is ever seen
  marking `fallito` a message the user can find in their Sent folder, this note is the
  first place to look: that symptom is precisely what `NO` looks like in production.

## Re-verify when

Google changes the Gmail API's documented behaviour, or a Workspace tenant with a
transport rule that rewrites headers is onboarded. This is a statement about a third
party, so it has a shelf life.
