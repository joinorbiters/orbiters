# The member area: a freelancer enters, reviews and changes what they sent

Date: 2026-09-10. Status: decided with Ivan the same day (ORB-62), being built in one
PR. Tracker: ORB-62 in `Hub v0 - signups and the company flow, deployed`.

## What Ivan asked for, and the decisions taken with him

After the wizard a freelancer has nothing to come back to: no login, no way to review
or change what they sent, no place where the perks are. Ivan asked on 2026-09-09 for an
area of their own with the information they gave, editable, the perks with PigroCRM in
evidence, and a second box marked coming soon. The card (ORB-62) laid out the options;
these are the answers, 2026-09-10:

- **The way in is a magic link by email.** No password anywhere: the person types the
  address they gave the wizard, we send a one-time link, the link opens a session. A
  password chosen at the end of the wizard was rejected because the rows already in
  production would have none; PigroCRM as identity provider is two products and a
  token exchange, not this step.
- **The provider is Resend**, called over plain `urllib` like the conversions endpoint,
  with the key in the host `.env` only. The SPF and DKIM records on joinorbiters.com are
  Ivan's part. The sender is «Orbiters <ciao@joinorbiters.com>»: warm, and somebody
  reads the replies.
- **Routes**: `/hub/accedi` (ask for the address), `/hub/entra` (where the link lands),
  `/hub/io` (the area), `/hub/io/modifica` (the form). The hub header gains «La tua
  area»; the thank-you page of the freelancer wizard says the area exists.
- **One PR** for core, API, web and the thank-you page, the migration in its own commit.

## What exists and is reused

- `freelancers.email` is already unique case-insensitively (`uq_freelancers_email_lower`,
  migration 0002), so «your row» is never ambiguous and nothing on that table changes.
- The admin's session mechanism (`orbiters_core.admin`): an opaque token, sha256 at
  rest, sliding expiry, revoked by deleting the row. The member session is the same
  shape in a second table and a second cookie, never the admin's.
- The comment thread on a freelancer (`orbiters_core.comments`, ORB-59): every change
  the person makes is a comment in it, so the admin sees what moved without an audit
  table.
- The wizard's validation (`FreelancerCreate` in `schemas.py`) and its field components
  (`apps/web/src/wizard/fields.tsx`): the edit form asks the same questions with the
  same controls and the same rules.
- The public token bucket (`orbiters_api.ratelimit.spend_one`): both auth endpoints
  spend from it, as the admin login does.

## Data: migration 0005

Two new tables, nothing conditional (0001 was the adoption; from 0002 on this history
owns the schema). Both hang on `freelancers.id` with `ON DELETE CASCADE`: deleting a
person deletes their way in.

```
magic_link_tokens   id, freelancer_id (FK, index), token_hash (64, unique),
                    created_at, expires_at, used_at (nullable)
member_sessions     id, freelancer_id (FK, index), token_hash (64, unique),
                    created_at, expires_at
```

A token is single use: `used_at` is set the moment it opens a session, and a used or
expired token answers like an unknown one. Expired and spent tokens of a person are
deleted lazily when that person asks for a new link; entering with one does not sweep,
so the login path stays a single write. Nothing needs a cron. `test_migrations.py`'s
`compare_metadata` check covers both tables.

## Core

### `orbiters_core.mail`

A small seam, so tests never send and production never guesses.

- `Mail(to, subject, text)`: a frozen dataclass. Plain text only: a login link needs no
  HTML and plain text is what arrives.
- `EmailSender` protocol: `send(mail) -> bool`. `True` when the provider accepted it;
  never raises, never logs the address or the key. Same discipline as `conversions.py`.
- `ResendSender(api_key, sender, http=...)`: `POST https://api.resend.com/emails` with
  `{"from", "to": [to], "subject", "text"}` and the bearer key, 10 seconds, over
  `urllib` behind the same `HttpCall` seam the conversions module uses, so a test hands
  it a fake and reads what would have gone out.
- `RecordingSender`: keeps every `Mail` in a list. For tests.
- `sender_from_settings(settings) -> EmailSender | None`: `None` when
  `resend_api_key` is empty. `None` is how the API knows to answer 503.
- `magic_link_mail(to, link, minutes) -> Mail`: the Italian text, in the voice of
  `docs/design/positioning.md`. Subject «Il tuo accesso a Orbiters». Body: the link, how
  long it lasts, and that ignoring the mail is fine if they did not ask for it.

### Settings (`config.py`, prefix `ORBITERS_`)

| Name | Default | Purpose |
|---|---|---|
| `resend_api_key` | `""` | Empty means no sender: the link request answers 503 |
| `mail_from` | `Orbiters <ciao@joinorbiters.com>` | The `from` header |
| `hub_url` | `https://joinorbiters.com/hub` | The link is `{hub_url}/entra?t={token}` |
| `magic_link_minutes` | `15` | Token lifetime |
| `member_session_days` | `30` | Sliding session lifetime, as the admin's |

`.env.example` and `docker-compose.yml` carry the first three; local development sets
`ORBITERS_HUB_URL=http://localhost:5180/hub`.

### `orbiters_core.members`

`MemberService(session, settings)`. The service never sends: it returns what to send.

- `request_link(email) -> Mail | None`. Lowercases and trims; `None` when no freelancer
  has that address; otherwise deletes that person's spent and expired tokens, writes a
  new one (`secrets.token_urlsafe(32)`, hash stored, raw in the link) and returns the
  mail to send. The caller decides what to do with `None`, and the API does the same
  thing in both cases.
- `enter(raw_token) -> tuple[MemberProfile, str] | None`. Hashes, finds an unused token
  past neither its expiry nor its `used_at`, marks it used, opens a session and returns
  the profile with the raw session token for the cookie. `None` for anything else.
- `resolve(raw_cookie) -> MemberProfile | None`: the admin's shape, sliding expiry.
- `close_session(raw_cookie)`.
- `profile(freelancer_id) -> MemberProfile`.
- `update(freelancer_id, MemberUpdate) -> MemberProfile`. Applies the seven fields the
  wizard asked, then writes one comment on the row listing what changed, in Italian:
  «Profilo aggiornato dalla persona: tariffa giornaliera, link». The author is the
  person's name after the change. No change, no comment. `stato`, `note` and the UTM
  columns are never touched here.
- `replace_cv(freelancer_id, bytes, filename, mime) -> MemberProfile`: `check_cv` as the
  wizard, then the comment «CV aggiornato dalla persona».
- `cv(freelancer_id) -> CvFile`: the person's own file and nobody else's, since the id
  comes from the session and never from the URL.

The email is not editable: it is the identity the link proved. Changing it is a new
application through the wizard, which `FreelancerService.apply` already treats as the
same person correcting theirs only when the address matches, so a changed address is a
new row. That is deliberate and written on the page.

### Schemas (`schemas.py`)

- `FreelancerFields`: the seven fields and their validators (`nome`, `cognome`,
  `linkedin_url`, `tariffa_giornaliera`, `posizione`, `remoto`, `links`), extracted from
  `FreelancerCreate`, which becomes `FreelancerFields` plus `email` and `utm`. Nothing
  the wizard accepts or refuses changes.
- `MemberUpdate(FreelancerFields)`: `extra="forbid"`.
- `MemberProfile`: `id`, `nome`, `cognome`, `email`, `linkedin_url`, `cv_filename`,
  `cv_size`, `tariffa_giornaliera`, `posizione`, `remoto`, `links`, `created_at`,
  `updated_at`. Never `stato`, `note`, the UTM six or the CV bytes.
- `LinkRequest(email: EmailStr)`, `EnterRequest(token: str)`, bounded.

## API (`orbiters_api.routers.members`, prefix `/api/hub`)

| Route | Answers | Notes |
|---|---|---|
| `POST /auth/link` | 202 `{"ok": true}` | `spend_one`. 503 «L'accesso via email non è ancora attivo» when there is no sender. The same 202 whether the address exists or not; the mail, when there is one, goes out in a `BackgroundTask` after the response, so a provider failure cannot tell the two cases apart either |
| `POST /auth/enter` | 200 `MemberProfile` + cookie | `spend_one`. 401 «Link non valido o scaduto. Chiedine un altro.» for a wrong, spent or expired token |
| `GET /me` | 200 `MemberProfile` | 401 without the cookie |
| `PATCH /me` | 200 `MemberProfile` | JSON `MemberUpdate`; 422 in FastAPI's shape names the field |
| `PUT /me/cv` | 200 `MemberProfile` | multipart `cv`; `check_cv`'s 422 as the wizard's |
| `GET /me/cv` | the PDF | `Content-Disposition: attachment`, the same filename sanitising the admin download does |
| `POST /me/logout` | 204 | deletes the session row and the cookie |

The cookie is `orbiters_user`: httpOnly, `secure` from `settings.cookie_secure`,
`SameSite=Lax`, `Path=/`, `max_age` = `member_session_days`. `deps.py` gains
`MEMBER_COOKIE`, `get_member` and `MemberDep`, beside the admin's and separate from it:
an admin cookie opens nothing here, a member cookie opens nothing there.

## Web (`apps/web`)

Four screens in the public `Shell`, and two touches on what exists.

- `/accedi`: one field, the address, and a button «Mandami il link». After the post the
  page says «Se sei dentro, ti abbiamo scritto: apri la mail e segui il link. Vale
  quindici minuti.» and says it whether the address exists or not. A 503 is shown as the
  API's sentence. A 429 as the client's usual one.
- `/entra?t=…`: posts the token on mount, then goes to `/io`. On 401 it says «Il link non
  è più valido» with a link to `/accedi`. The mail points here and never at the API, so
  a scanner that fetches every link in a message cannot spend the token: it does not run
  the page.
- `/io`: a guard first (`useMember`, the shape of `AdminLayout`'s guard, sending to
  `/accedi` without a session). Then the answers under the wizard's own questions as
  labels («Come ti chiami?», «Quanto costa una tua giornata?» …), the CV as name, size
  and a download link, «Modifica» and «Esci». Below, two boxes: «PigroCRM è tuo, gratis»
  in evidence, one sentence and the link to `https://pigro.joinorbiters.com/app/registrati`;
  and «Altro in arrivo», static, muted. The email is shown and marked as the address we
  write to, not editable, with the sentence about a new application.
- `/io/modifica`: one page, every question at once, not a wizard: the person is
  correcting, not answering for the first time. It renders `FREELANCER_STEPS` minus the
  email step, with each step's `render` and `validate` as they are; the CV step is made
  optional here (`null` means keep the one we have). «Salva» runs `PATCH /me` and, when a
  file was chosen, `PUT /me/cv`; a 422 naming a field is shown under that field. Back to
  `/io` on success.
- `Shell`: «La tua area» in the header, to `/io`.
- `Thanks`, freelancer branch: one more sentence, «Vuoi rileggere o cambiare quello che
  ci hai mandato? Entra nella tua area», to `/accedi`.

`lib/api.ts` gains a `member` namespace and the `MemberProfile` type; `lib/member.tsx`
the hooks (`useMember`, `useRequestLink`, `useEnter`, `useUpdateProfile`,
`useReplaceCv`, `useMemberLogout`), the shape of `lib/auth.tsx`.

## Security

- Tokens and session tokens are stored as sha256 only; the raw value travels in the
  link or the cookie and nowhere else.
- `/auth/link` and `/auth/enter` spend from the public bucket; the link request answers
  identically for a known and an unknown address, and the send is deferred so timing and
  failures do not distinguish them either.
- The member's routes read the id from the session and never from the URL: there is no
  `/me/{id}` and no way to name another row.
- `MemberProfile` carries no admin field and no attribution; the CV bytes have their
  own route.
- The cookie carries the admin cookie's flags and lifetime; logout deletes the row.

## Testing

- Core, `test_members.py`: a link for an unknown address returns `None` and writes no
  token; a known address gets a token and the mail carries `/entra?t=`; the token opens
  a session once and never twice; an expired token does not; `resolve` slides the
  expiry; `update` changes the fields and writes one comment naming exactly the changed
  ones, and none when nothing changed; `replace_cv` refuses a non-PDF like the wizard and
  writes its comment; `stato` and `note` survive an update untouched.
- Core, `test_mail.py`: `ResendSender` sends the expected JSON to the expected URL with
  the bearer header, answers `True` on 200 and `False` on 4xx, 5xx and a network error,
  and never raises; `sender_from_settings` is `None` without a key.
- API, `test_member_api.py`: 503 without a sender; 202 for both a known and an unknown
  address, and the recording sender holds exactly one mail; the link from that mail
  enters and sets an httpOnly, secure cookie; every `/me` route is 401 without it; a
  member with a cookie reads their own row and cannot reach the admin routes with it,
  nor the admin the member routes; the PATCH changes the row and the admin thread shows
  the comment; the CV download is the member's own file; logout kills the session.
- Migrations: `compare_metadata` sees the two new tables.
- Web, vitest: `/accedi` shows the same sentence for two different addresses; the edit
  page's validators refuse what the wizard refuses and accept a missing CV; `/entra`
  posts the token from the URL.
- By hand, for the PR's screenshots: the four pages at 1440×900, with a fixture
  freelancer and the link read from the recording sender's output in development.

## Deploy

The stack deploys as every stack here (`docs/adding-a-project.md` §7): preview on the
green trunk, production on `hub-v<semver>` when Ivan asks. Before the tag, on the host,
by hand and not a release: `ORBITERS_RESEND_API_KEY` and `ORBITERS_MAIL_FROM` in
`/opt/hub/.env`, and the SPF and DKIM records Resend gives for joinorbiters.com. Until
the key is there `/hub/accedi` answers with the 503 sentence, which is the honest state.

## Deliberately not in this step

- The community page on the website saying the area exists: ORB-19 removed «Accedi» from
  its footer at Ivan's request and ORB-71 is moving the front door. Its own card.
- A company area: the mechanism is reusable (`entity_type` would do for tokens and
  sessions too), but nobody asked for it yet.
- A flag saying a member activated PigroCRM, a notification to the admin on a change
  (the thread covers it), a password, and any change to the wizards themselves.
- HTML mail, a second provider, a queue: one plain-text mail per login is the whole
  volume.
