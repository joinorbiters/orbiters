# A freelancer card born from a signup, completed by the person

Date: 2026-09-11. Status: decided with Ivan the same day (ORB-155), being built in one
PR. Tracker: ORB-155 in `Hub v0 - signups and the company flow, deployed`.

## What Ivan asked for, and the decisions taken with him

«Iscrizioni» holds 53 addresses on 2026-09-11: 29 with a name, 16 with a LinkedIn URL,
24 with nothing but the address. Only one of them has a freelancer card, Ivan's own,
written by the wizard. Ivan asked for each of them to be researched on the public web
(LinkedIn, personal sites, what a search for the name and the address turns up) and for
the result to become a profile inside the hub, readable from the admin area.

The first design offered a table of its own, `signup_profiles`, with a state per row
(`trovato`, `incerto`, `non_trovato`) and a detail page under «Iscrizioni». Ivan turned
it down: «questi dati però devono popolare le stesse info di destinazione di
/hub/freelance». The profile is the freelancer card the wizard creates, and nothing
else. From that follow the decisions below, all taken on 2026-09-11:

- **The card can be incomplete.** The wizard asks for a CV, a daily rate, a position and
  a remote option, and none of those is on the public web. So a card may exist without
  them, and the person completes it themselves: the member area already lets the owner
  of an address in with a magic link, and its edit form already asks the wizard's
  questions.
- **Who wrote the answers last is recorded.** A column `compilata_da`, `persona` or
  `admin`. The wizard and the member area write `persona`; a card written from a signup
  is `admin`. Research never overwrites what a person wrote: a second research call on
  an `admin` card replaces the researched fields, a call on a `persona` card is refused.
- **Read-only in the admin area.** Corrections go through the MCP tool or the API.
- **No «non trovato» anywhere.** With the card as the target there is no row to hang a
  negative result on. A card is created only when name and surname are reliable; the
  people not found are listed in the closing comment of ORB-155, not stored.
- **The signup row is never edited by the research.** What the person typed on the
  landing stays as typed; the card is where the found data goes.
- **Sources go in the thread.** The comment thread on a freelancer (ORB-59) is where the
  hub already records what changed and who changed it. The research leaves one comment
  naming its sources, signed «Claude».
- **All the way to production.** PR, merge, tag `hub-v0.9.0`, then the 52 cards written
  through the API with an admin session.

A note Ivan has seen: these people gave an address and a name, not a consent to
enrichment. The processing stays on public professional data, and a line in the privacy
policy about it is Ivan's part, outside this PR.

## What exists and is reused

- `Freelancer` (`orbiters_core.models`): one row per address, `uq_freelancers_email_lower`
  (migration 0002). `FreelancerService.apply` upserts by address for the wizard.
- `FreelancerFields` (`orbiters_core.schemas`): the seven answers with their rules, shared
  by `FreelancerCreate` and `MemberUpdate`. `FreelancerDraft` below reuses its validators
  and loosens only what the web cannot answer.
- `MemberService` (`orbiters_core.members`): the magic link by email, `update` with a
  comment naming what moved, `replace_cv`. Unchanged in shape.
- `CommentService` (`orbiters_core.comments`): the thread.
- `SignupService.list_recent` and `SignupListItem`: the «Iscrizioni» list.
- The admin area's cookie and `AdminDep`; the MCP server's `_run` and its per-call session.
- Web: `pages/admin/lists.tsx` (freelancer list, freelancer detail, signups list),
  `pages/member/Area.tsx` and `Modifica.tsx`, `lib/api.ts` (hand-written client),
  `lib/member.tsx` (`toApplication`, `toUpdate`), `pages/FreelancerWizard.tsx`
  (`FREELANCER_STEPS`, whose `cv` step `Modifica` already marks optional).

## The data

Migration `0007_freelancer_card_from_signup`, on `freelancers`, safe on the table in
production (one row, Ivan's, complete):

- `cv_bytes`, `cv_filename`, `cv_mime`, `cv_size`, `tariffa_giornaliera`, `posizione`,
  `remoto` become nullable. Nothing else about them changes: the same types, the same
  widths.
- `compilata_da VARCHAR(10) NOT NULL DEFAULT 'persona'`, added with the server default so
  the existing row reads `persona`, which is true of it. The model declares
  `default="persona"` and no server default, as `stato` does; the test that compares the
  migrated schema with the metadata (`test_migrations.py`) keeps ignoring server
  defaults, as it does today for `created_at`.
- Downgrade sets the columns back to `NOT NULL` and drops `compilata_da`. It fails on a
  table that holds an incomplete card, on purpose: a downgrade that invents a CV is worse
  than one that stops.

The model: the seven columns become `Mapped[... | None]`, `compilata_da: Mapped[str]`
with `COMPILATA_DA = ("persona", "admin")` beside `FREELANCER_STATES`.

## Core

### Schemas

- `FreelancerDraft(BaseModel)`, `extra="forbid"`: `nome` and `cognome` required with the
  rules of `FreelancerFields`; `linkedin_url`, `posizione`, `tariffa_giornaliera`,
  `remoto` optional (`None` means «not found»); `links` as in `FreelancerFields`;
  `fonti: list[SafeStr]`, one to ten https URLs, required and non-empty, because a card
  written from research with no source is a card nobody can check. Validators are the
  ones `FreelancerFields` already has, called on the same names.
- `FreelancerRead`: `cv_filename`, `cv_mime` become `str | None`, `cv_size: int | None`,
  `tariffa_giornaliera: Decimal | None`, `posizione: str | None`, `remoto: str | None`;
  new `compilata_da: str` and `completa: bool`, computed as «CV present and rate and
  position and remote all present». `MemberProfile` gets the same optionals and the same
  `completa`.
- `SignupListItem` gains `freelancer_id: UUID | None`: the card with the same address,
  case-insensitively, or `None`. Filled by `SignupService.list_recent` with one outer join
  on `lower(email)`, not a query per row.

### `FreelancerService`

- `apply` sets `compilata_da = "persona"` on the row it writes, new or existing, so a
  person who runs the wizard on top of a researched card takes it over.
- `draft_from_signup(signup_id: UUID, data: FreelancerDraft, autore: str) -> FreelancerRead`:
  1. The signup, or `NotFound("signup", id)`.
  2. The card with that address, if any. If it exists and `compilata_da == "persona"`,
     `ValidationFailed("freelancer", "email", "la persona ha già compilato la sua scheda")`.
  3. New row: `email` from the signup, the six `utm_*` from the signup, the CV columns
     `None`, `stato = "nuovo"`, `compilata_da = "admin"`. Existing `admin` row: the
     researched fields replaced (`nome`, `cognome`, `linkedin_url`, `posizione`,
     `tariffa_giornaliera`, `remoto`, `links`), `stato`, `note`, the CV and the
     attribution left alone.
  4. Commit, with the same `IntegrityError` retry `apply` has for two first writes racing
     on one address.
  5. One comment in the thread, author `autore`: «Scheda creata dall'iscrizione del
     <date>. Fonti: <url>, <url>» for a new row, «Scheda aggiornata dalla ricerca. Fonti:
     …» for a replaced one.
  6. `FreelancerRead` of the row, with `commenti` filled as `get` fills it.
- `cv` raises `NotFound("cv", id)` when the row has no CV; the API turns it into a 404 as
  it does for a missing row.

### `MemberService`

- `update` sets `compilata_da = "persona"` whenever it writes, and counts that as a change
  even if the seven answers are equal, so an `admin` card the person confirms unchanged
  becomes theirs. The comment stays «Profilo aggiornato dalla persona: …» when something
  moved, and «Scheda confermata dalla persona» when nothing did but the ownership.
- `replace_cv` sets `compilata_da = "persona"` too. Its comment becomes «CV caricato
  dalla persona» when the row had none, «CV aggiornato dalla persona» otherwise.
- `cv` raises `NotFound("cv", id)` on a row without one.

## API

- `POST /api/hub/signups/{signup_id}/scheda`, admin cookie, body `FreelancerDraft`,
  `201` with `FreelancerRead`; `404` for an unknown signup, `422` naming `email` for a
  `persona` card, `422` from pydantic for a bad body. The author of the comment is the
  logged-in admin's name.
- `GET /api/hub/signups`: each item carries `freelancer_id`.
- `GET /api/hub/freelancers/{id}/cv` and `GET /api/hub/me/cv`: `404` when the card has no
  CV.
- Everything else keeps its path and its status codes; the response shapes gain the
  nullable fields, `compilata_da` and `completa`.

## MCP

- `create_freelancer_from_signup(signup_id: str, nome: str, cognome: str, fonti: list[str],
  linkedin_url: str | None = None, posizione: str | None = None, tariffa_giornaliera:
  str | None = None, remoto: str | None = None, links: list[str] | None = None, autore:
  str | None = None)`, backed by `FreelancerService.draft_from_signup`, author «MCP» when
  not given. The docstring says in Italian what it is for and that it refuses a card the
  person has filled in.
- `list_signups` items carry `freelancer_id`; `list_freelancers` and `get_freelancer`
  carry `compilata_da` and `completa`. The «no tool subscribes or applies on somebody's
  behalf» test keeps holding: the new name contains none of the banned words, and the
  tool writes an admin's research, not a person's application.

## Web

- `lib/api.ts`: `Freelancer` gains the nullable fields, `compilata_da`, `completa`;
  `Signup` gains `freelancer_id`; `MemberProfile` gains the nullable fields and
  `completa`. No client call for the POST: the admin area is read-only here by decision.
- «Iscrizioni» (`AdminSignups`): a «Scheda» column between «LinkedIn» and «Da». A row with
  a `freelancer_id` links to `/admin/freelance/$id` with the text «apri»; otherwise «—».
- Freelancer list (`AdminFreelancers`): «Posizione», «Tariffa», «Dove» print «—» when
  `null`; the «Stato» cell shows a second pill «Da completare» when `completa` is false.
- Freelancer detail (`AdminFreelancerDetail`): the CV button appears only with a CV; the
  three rows print «—» when `null`; the header carries the «Da completare» pill; a new row
  «Scheda» says «compilata dalla persona» or «scritta dall'admin, da completare» /
  «scritta dall'admin». The thread already shows the sources.
- Member area (`Area`): when `completa` is false, a bordered notice above the list:
  «La tua scheda è incompleta. Aggiungi CV, tariffa, posizione e modalità di lavoro
  perché le aziende possano trovarti.» with a button to `/io/modifica`. The CV row shows
  «Nessun CV» with no link when there is none. `toApplication` maps `null` to `''`.
- Edit form (`Modifica`): the `cv` step is optional only when the profile has a CV;
  without one it is required with the wizard's own message. Everything else unchanged:
  `MemberUpdate` already requires the other answers, which is the completion.

## Testing

- Core: migration test unchanged and green (metadata matches); `draft_from_signup`
  creates an incomplete card with the signup's attribution and one comment with the
  sources; a second call replaces the researched fields and leaves `stato`, `note`, CV;
  a call on a `persona` card is refused naming `email`; an unknown signup is `NotFound`;
  `apply` and `MemberService.update`/`replace_cv` flip `compilata_da`; `cv` on a card
  without one is `NotFound`; `FreelancerDraft` refuses an empty `fonti` and an http source;
  `list_recent` on signups fills `freelancer_id` case-insensitively.
- API: `POST /signups/{id}/scheda` is a 401 without the cookie, 201 with the card and the
  comment signed by the admin, 404 on a wrong id, 422 on a `persona` card; the signups
  list carries `freelancer_id`; `GET .../cv` is 404 on a CV-less card; the member routes
  read an incomplete profile with `completa: false` and complete it with `PATCH /me` plus
  `PUT /me/cv`.
- MCP: `create_freelancer_from_signup` writes the card and the comment; the tool-name ban
  test still passes.
- Web (vitest): «Iscrizioni» links a row with a card and prints «—» otherwise; the
  freelancer list and detail render an incomplete card without crashing and show the
  pill; `Area` shows the notice and hides the CV link; `Modifica` refuses to save an
  incomplete card without a CV.
- Screenshots: before/after pairs for «Iscrizioni», the freelancer detail and `/hub/io`,
  taken as `docs/pr-screenshots/README.md` says.

## The research, after the release

Done by the agent, by hand, one person at a time, from what the signup gives: the address,
the name when present, the LinkedIn URL when present. Sources are the LinkedIn profile
found by search (the page itself refuses fetches; the search snippet, the vanity URL and
the personal site are what is read), the personal site or portfolio when the address's
domain is one, GitHub and similar when the name and the field match. A card is written
only when the name and surname are established beyond the address alone, or the address
carries them; `posizione` is the headline as the person states it, `links` are the sites
found, `tariffa_giornaliera` and `remoto` are left `None` because nothing public states
them. Ivan's own card is skipped. Who was not found is listed in the closing comment on
ORB-155 with the reason, and in the report to Ivan.
