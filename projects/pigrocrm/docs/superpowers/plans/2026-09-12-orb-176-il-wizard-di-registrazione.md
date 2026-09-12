# ORB-176, il wizard di registrazione: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Creare uno spazio chiede l'email e il nome, in due passi e senza password; chi ha già uno spazio riceve il link per entrare invece di crearne un altro; chi è membro della community trova il nome già scritto; il 201 apre la sessione e la pagina atterra sulla Home; parte la mail di benvenuto.

**Architecture:** Monorepo Orbiters, progetto `projects/pigrocrm/` (percorsi relativi; comandi dalla radice, nel worktree `../pigrocrm-orb176` creato da `origin/main` **dopo** il merge di ORB-172 e ORB-173, che portano `MagicLinkService`, `pigrocrm.core.mail`, `POST /api/auth/link` e `POST /api/tenants/membro`). In core: `UserCreate.password` opzionale, accettato solo dal sistema; `welcome_mail` in `mail.py`. In api: `POST /api/tenants` senza password, che apre la sessione e manda il benvenuto. In web: `registrati.tsx` riscritto a due passi. Nessuna migrazione (la password nullable è di ORB-172).

**Tech Stack:** Python 3.13, FastAPI, Pydantic 2; React 19, TanStack Router, vitest.

**Spec:** `projects/pigrocrm/docs/superpowers/specs/2026-09-12-onboarding-product-led-design.md` §6.4 e §6.6.

## Global Constraints

- Commit in inglese, Conventional Commits, prima persona, **nessun trailer AI**; ultima riga `ORB-176.`; `git add` con pathspec.
- La community è la via veloce, non un cancello: `membro: false` non blocca nulla.
- La sessione si apre al 201; il primo ingresso via link del vero titolare revoca quella sessione (ORB-172 lo garantisce, non si tocca qui).
- Nessun indirizzo email nei log; la mail di benvenuto non contiene la password (non c'è più).
- I test API degli spazi girano contro un registro vero (`spaces_client`); mai due pytest DB-backed insieme.
- `POST /api/tenants/membro` risponde `{membro, nome, cognome, spazi: int}` (ORB-173, dopo la revisione: `spazi` è un conteggio).

---

### Task 1: un admin senza password, solo dal sistema (core)

**Files:**
- Modify: `packages/core/src/pigrocrm/core/auth/schemas.py` (`UserCreate.password: str | None = None`)
- Modify: `packages/core/src/pigrocrm/core/auth/service.py` (`create`)
- Modify: `packages/core/src/pigrocrm/core/tenants/schemas.py` (`TenantSignup.password: str | None = None`)
- Test: `packages/core/tests/test_auth_users.py`

- [ ] **Step 1: Il test**

```python
def test_only_the_system_may_create_a_user_without_a_password(db_session: Session) -> None:
    service = UserService(db_session)
    admin = service.create(
        UserCreate(email="capo@x.it", password="lunghissima1", nome="Capo", nome_ruolo="admin"),
        Actor.system(),
    )
    actor = Actor(id=admin.id, type="user", role="admin")
    with pytest.raises(ValidationFailed):
        service.create(UserCreate(email="link@x.it", password=None, nome="Link"), actor)
    created = service.create(UserCreate(email="link@x.it", password=None, nome="Link"), Actor.system())
    row = UserRepository(db_session).get(created.id)
    assert row is not None and row.password_hash is None
```

(Il costruttore di `Actor` e il campo del ruolo vanno letti in `actor.py`; `ruolo` in `UserCreate`.)

- [ ] **Step 2: Fallisce** (`password: str` non accetta `None`).

- [ ] **Step 3: Il codice**

`UserCreate.password: str | None = None` con il commento «`None` only for a space's first admin, created by the wizard (spec 2026-09-12 §6.4): the person enters with a link by mail. `UserService.create` refuses it from anyone but the system.» In `create`, prima del controllo di lunghezza:

```python
        if data.password is None:
            if actor.type != "system":
                raise ValidationFailed("user", "password", "obbligatoria", expected="una password")
        elif len(data.password) < MIN_PASSWORD_LENGTH:
            raise ValidationFailed(...)  # as today
```

e `password_hash=hash_password(data.password) if data.password is not None else None`. `TenantSignup.password: str | None = Field(default=None, min_length=1, max_length=1024)`; il router `POST /api/tenants` continua ad accettarla (retrocompatibile) ma il wizard non la manda.

- [ ] **Step 4: Test, lint, tipi, commit** `feat(core): a space's first admin may have no password, and only the system may create one`.

---

### Task 2: la mail di benvenuto (core)

**Files:**
- Modify: `packages/core/src/pigrocrm/core/mail.py` (`welcome_mail`)
- Test: `packages/core/tests/test_mail.py`

- [ ] **Step 1: Il test**

```python
def test_the_welcome_mail_says_where_to_enter_and_what_to_do_first() -> None:
    mail = welcome_mail("ada@x.it", "Ada", "https://pigro.test/ada/app/login", membro=True)
    assert mail.subject == "Il tuo spazio PigroCRM è pronto"
    assert "https://pigro.test/ada/app/login" in mail.text
    assert "assistente" in mail.text.lower() and "dati fiscali" in mail.text and "primo cliente" in mail.text
    assert "Orbiters" not in mail.text.split("PigroCRM")[-1] or membro is False  # no community pitch for a member
    guest = welcome_mail("bob@x.it", None, "https://pigro.test/bob/app/login", membro=False)
    assert "joinorbiters.com/hub/freelance" in guest.text
```

- [ ] **Step 2: Il codice.** `welcome_mail(to, nome, login_url, *, membro) -> Mail`: saluto («Ciao Ada,» o «Ciao,»), «il tuo spazio PigroCRM è pronto», il bottone «Entra nel tuo spazio» su `login_url` con la frase «scrivi la tua email, ti arriva un link», una riga sull'assistente («Collega Claude al tuo spazio: dalla Home, «Collega l'assistente»»), i tre primi passi come frasi (dati fiscali, primo cliente, prima offerta), e per `membro=False` un paragrafo su Orbiters con `https://joinorbiters.com/hub/freelance`. Voce di `docs/design/positioning.md`, cornice `_frame`. Ogni valore esterno passa da `html.escape`.

- [ ] **Step 3: Test, lint, commit** `feat(core): the welcome mail of a new space`.

---

### Task 3: `POST /api/tenants` apre la sessione e manda il benvenuto (api)

**Files:**
- Modify: `apps/api/src/pigrocrm_api/routers/tenants.py` (`signup`)
- Modify: `packages/core/src/pigrocrm/core/tenants/service.py` (`provision` accetta `password=None`, e risponde anche l'`id` dell'admin creato: aggiungere `admin_id: UUID` a `TenantRead`? No: `TenantRead` è la riga del registro. Restituire una `ProvisionedSpace(tenant: TenantRead, admin: UserRead)` da `provision`, e adattare i chiamanti: il router e i test)
- Test: `apps/api/tests/test_tenants_api.py`

- [ ] **Step 1: I test**

```python
def test_signing_up_opens_the_session_and_mails_the_welcome(spaces_client: TestClient) -> None:
    from pigrocrm.core.mail import RecordingSender
    from pigrocrm_api.routers.auth import get_sender

    recording = RecordingSender()
    spaces_client.app.dependency_overrides[get_sender] = lambda: recording  # type: ignore[attr-defined]
    created = spaces_client.post("/api/tenants/", json={"slug": SLUG, "nome": "Ada Lovelace", "email": "ada@studio.it"})
    assert created.status_code == 201, created.text
    assert created.headers["Location"] == f"/{SLUG}/app/"
    assert any(f"Path=/{SLUG}/" in c for c in created.headers.get_list("set-cookie"))
    # Already in: no login, the space's own `me` answers the admin.
    assert spaces_client.get(f"/{SLUG}/api/auth/me").json()["email"] == "ada@studio.it"
    assert len(recording.sent) == 1 and recording.sent[0].to == "ada@studio.it"
    assert f"/{SLUG}/app/login" in recording.sent[0].text
    # The password form knows no password for this admin.
    assert spaces_client.post(f"/{SLUG}/api/auth/login", json={"email": "ada@studio.it", "password": "qualunque11"}).status_code == 401


def test_signing_up_without_a_sender_still_creates_the_space(spaces_client: TestClient) -> None:
    created = spaces_client.post("/api/tenants/", json={"slug": SLUG, "nome": "Ada", "email": "ada@studio.it"})
    assert created.status_code == 201, created.text
```

Aggiornare i test esistenti che leggono `Location == /{SLUG}/app/login` (`test_signing_up_creates_a_space_that_serves_its_own_data`) alla nuova `Location`, e quello che fa il login con la password dello spazio: lo `SIGNUP` di quel file passa ancora una password, quindi il login resta possibile lì (il router la accetta ancora).

- [ ] **Step 2: Il codice.** In `provision`, `UserCreate(..., password=data.password)` funziona già con `None` dopo Task 1; `provision` restituisce `ProvisionedSpace(tenant, admin)`. Nel router:

```python
@router.post("/", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
def signup(data, registry, settings, request, response, background, sender: SenderDep) -> TenantRead:
    space = TenantService(registry, settings).provision(data)
    # Registering is entering (spec 2026-09-12 §6.4): the cookies the space's own login
    # would set, at the space's path; the browser accepts them from the root's response,
    # it is the same host. The first link entry of the real owner revokes this session.
    engine = create_engine(tenant_database_url(settings, tenant_database_name(space.tenant.slug)), future=True)
    try:
        with session_factory(engine)() as session:
            refresh = RefreshTokenService(session).issue(space.admin.id, settings)
    finally:
        engine.dispose()
    path = f"/{space.tenant.slug}/"
    _set_cookie(response, ACCESS_COOKIE, issue_access_token(space.admin.id, space.admin.ruolo, settings), settings.access_token_minutes * 60, secure=settings.cookie_secure, path=path)
    _set_cookie(response, REFRESH_COOKIE, refresh, settings.refresh_token_days * 86400, secure=settings.cookie_secure, path=path)
    response.headers["Location"] = f"/{space.tenant.slug}/app/"
    if sender is not None:
        login_url = f"{_origin(request, settings)}/{space.tenant.slug}/app/login"
        background.add_task(_send, sender, welcome_mail(space.tenant.owner_email, data.nome, login_url, membro=data.membro))
    return space.tenant
```

`_set_cookie`, `_origin`, `_send`, `SenderDep` si importano da `routers/auth.py` (o si spostano in un modulo `pigrocrm_api/session_cookies.py` condiviso dai due router: preferibile, con un commit di spostamento a sé). `TenantSignup` gain `membro: bool = False`, che il wizard passa dal passo 1, così la mail sa se raccontare Orbiters.

- [ ] **Step 3: Test, lint, tipi, commit** `feat(api): signing up opens the space's session and mails the welcome`.

---

### Task 4: il wizard (web)

**Files:**
- Modify: `apps/web/src/lib/api-types.ts` (rigenerare da `create_app().openapi()`: `POST /api/tenants/membro`, `TenantSignup` senza password obbligatoria, `membro`)
- Rewrite: `apps/web/src/routes/app/registrati.tsx`
- Rewrite: `apps/web/src/routes/app/registrati.test.tsx`

- [ ] **Step 1: I test** (stesso impianto di oggi: `api.GET/POST` stubbati, router finto). Cinque casi:
  1. Passo 1 → `POST /api/tenants/membro` con l'email; con `{membro: true, nome: "Ada", cognome: "Lovelace", spazi: 0}` il passo 2 mostra «Sei dei nostri: ciao Ada» e il nome «Ada Lovelace» già nel campo, l'indirizzo `pigro.test/ada-lovelace è libero` dopo la `GET disponibile`.
  2. Con `{membro: false, spazi: 0}` il passo 2 ha il nome vuoto e la riga «Non sei ancora nella community? Puoi entrare comunque…».
  3. Con `spazi: 1` la card dice «Hai già uno spazio» e il bottone chiama `POST /api/auth/link` con l'email, poi mostra «Controlla la posta»; «Vuoi crearne un altro?» porta al passo 2.
  4. «cambia» apre il campo dell'indirizzo; un indirizzo riservato mostra la ragione locale prima di chiamare il server (come oggi).
  5. «Crea lo spazio» chiama `POST /api/tenants/` con `{slug, nome, email, membro}` e **senza** password, e su 201 naviga a `/<slug>/app/` (`go` iniettabile come in `entra.tsx`); un 409 mostra la frase e resta al passo 2.

- [ ] **Step 2: Il componente.** Stato: `step: 1 | 2`, `email`, `member: {membro, nome, cognome, spazi} | null`, `nome`, `slug`, `slugTouched`, `editingSlug`, `availability` (come oggi), `busy`, `error`, `linkSent`. Passo 1: titolo «Crea il tuo spazio», sottotitolo «1 di 2», campo Email, «Avanti» (disabled senza email); su risposta con `spazi > 0` la card «Hai già uno spazio» (senza nominarlo: la mail lo fa) con «Mandami il link per entrare» e «Vuoi crearne un altro?». Passo 2: «2 di 2», «Come si chiama il tuo spazio?», campo Nome (precompilato con `nome cognome` se membro), riga dell'indirizzo con «cambia», la riga sulla community per i non membri, «Creando lo spazio accetti i termini e la privacy» con i link a `https://joinorbiters.com/termini` e `/privacy`, bottone «Crea lo spazio» (disabled finché l'indirizzo non è libero), «Indietro». Nessun campo password. Il bottone «Ho già un account» di oggi diventa «Ho già uno spazio: entra» → `/app/login`.

- [ ] **Step 3: lint, test, build, commit** `feat(web): the signup is two steps, email then name, with no password, and lands inside the space`.

---

### Task 5: verifica, DECISIONS, PR

- Riga in `DECISIONS.md`: chi non è nella community può creare uno spazio (la community è la via veloce); la sessione si apre alla registrazione e il primo link del titolare la revoca (rimando a ORB-172); il nome del membro viene dall'hub.
- Suite Python completa in serie, `pnpm --filter web lint/test/build`, e2e se `:8000` è libero (`auth.spec`, `crm.spec` toccano il login; la registrazione non ha e2e oggi: aggiungerne uno che crea uno spazio dal wizard e vede la Home dello spazio è il test di accettazione della card).
- Screenshot: la pagina di registrazione prima/dopo (Vite dev senza API basta per il passo 1; per il passo 2 serve una risposta finta di `/api/tenants/membro`: `page.route` in Playwright).
- PR, revisione indipendente, `In Review`, merge con merge commit, `Done` con l'evidenza; nota a Ivan: produzione al prossimo tag, con `PIGROCRM_RESEND_API_KEY` e `PIGROCRM_PUBLIC_URL` nel `.env`.
