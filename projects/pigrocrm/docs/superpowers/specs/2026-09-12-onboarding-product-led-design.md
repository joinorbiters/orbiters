# Onboarding product-led — da «spazio creato» a «spazio attivato»

**Data:** 2026-09-12 (revisione 2, dopo le indicazioni di Ivan)
**Ambito:** il percorso che porta una persona dalla landing a uno spazio PigroCRM che usa
davvero: la registrazione, il primo ingresso, la prima sessione, il ritorno. Il
provisioning (un database per spazio, spec 2026-09-08) non cambia: cambia chi è la
persona che entra (la stessa della community), cosa uno spazio contiene quando nasce,
come ci si entra e cosa si vede la prima volta.

Il documento è scritto dal punto di vista di un growth hacker che ha letto il codice e i
dati di produzione. Prima i dati, poi la diagnosi, poi le specifiche.

Indicazioni di Ivan del 2026-09-12 che questa revisione recepisce: chi è già nella
community entra con quell'identità e imposta solo il nome; la registrazione diventa un
wizard più semplice; gli stati di pipeline esistono di default; il template predefinito
dei documenti è caricato per tutti e ognuno lo personalizza; il pulsante per collegare
l'MCP lo fa Ivan a parte, ma la Home deve spingere forte quella funzione; il login è
unico con quello della community; la misura arriverà con PostHog, non ora; per la posta
si usa Resend.

---

## 1. I dati di produzione (letti il 2026-09-12, sola lettura)

Otto spazi creati fra il 9 e l'11 settembre da sette persone.

| Metrica | Valore |
|---|---|
| Spazi creati | 8 |
| Persone distinte | 7 |
| Login dopo la creazione | 8 su 8 (è obbligatorio) |
| Tornati almeno una seconda volta | 2 su 8, e uno dei due è Lorenzo |
| Spazi con almeno un cliente, deal, fattura, ora o template | **0 su 8** |
| Stati di pipeline configurati | 0 in tutti gli spazi |

Sei spazi su otto hanno esattamente una sessione, aperta pochi secondi dopo la
registrazione: la persona ha riscritto le credenziali, ha visto la Home vuota e non è
tornata. **L'acquisizione funziona, l'attivazione è zero, la retention è zero.**

## 2. Il funnel oggi, passo per passo

| Passo | Cosa succede | Attrito |
|---|---|---|
| Sito `joinorbiters.com` (landing e `/pigrocrm`) | Ogni bottone manda al wizard della community, `/hub/freelance` (ORB-160, ORB-165): il CRM è il perk, non la porta | Nessuno: è la scelta del prodotto |
| Pagina «Grazie» dell'hub e area membro | Link a `pigro.joinorbiters.com/app/registrati`: le sole due porte verso il CRM | La persona ha appena dimostrato chi è nell'hub, e il CRM non lo sa |
| Form di registrazione | Nome, indirizzo dello spazio, email, password ≥ 10 | Una password nuova per chi nella community entra senza password; un utente ha creato due spazi (`mohamed`, poi `mohamed-el-moumini`) |
| Card «Il tuo spazio è pronto» | → `/<slug>/app/login` | **Seconda autenticazione**: la persona riscrive email e password appena scelte |
| Prima sessione | Home con grafici «Nessun dato nel periodo» | Nessuna indicazione su cosa fare |
| Primo deal | Zero stati di pipeline: «nessuno stato aperto configurato» | La cura è un bottone «Ripristina predefiniti» in Impostazioni |
| Prima offerta | Zero template; i predefiniti arrivano solo dalla CLI | La promessa della landing non è raggiungibile |
| Prima fattura | Emittente e profilo fiscale vuoti | Due pannelli che niente indica come prerequisito |
| Assistente AI | «Imposta `PIGROCRM_TOKEN` di chi lo userà»; l'MCP è stdio sul database | Il differenziatore non è raggiungibile (Ivan ci sta lavorando a parte) |
| Password dimenticata | Non esiste; `pigrocrm resetpassword` è CLI del server | Chi dimentica la password perde lo spazio |
| Posta, misura | Nessun mittente, nessun evento | Nessun benvenuto, nessun richiamo, funnel leggibile solo a mano |

## 3. Diagnosi

1. **Due identità per la stessa persona.** Nella community si entra con un link via
   mail; in PigroCRM con una password scelta apposta. La persona che arriva dall'area
   membro ha appena dimostrato chi è, e le si chiede di inventare una seconda identità.
2. **Time-to-value infinito.** Non c'è un percorso dalla Home vuota a un primo
   risultato; la configurazione è nascosta in sette tab di Impostazioni.
3. **Il prodotto nasce rotto per disegno.** I predefiniti sono un'azione manuale pensata
   per la radice; per uno spazio sono un difetto.
4. **Doppia porta.** Registrarsi e poi rifare il login è dove un prodotto product-led
   perde di più.
5. **Nessun ciclo di vita.** Senza posta non c'è benvenuto né ritorno.
6. **La funzione che vende non è in vetrina.** L'assistente AI è la promessa più forte
   della landing e nell'app è una voce «Token» in fondo alla sidebar.

## 4. North star e metriche

**North star: spazi attivati.** Uno spazio è attivato quando, entro sette giorni dalla
creazione, ha almeno un cliente **e** almeno una di queste: un deal, un documento, una
registrazione di ore, una fattura. Metrica di secondo livello, perché è la promessa:
**spazi con l'assistente collegato** (almeno un token personale creato).

| Metrica guida | Oggi | Obiettivo a 30 giorni dal rilascio |
|---|---|---|
| Spazi con profilo emittente salvato entro il primo giorno | 0 % | 50 % |
| Tempo al primo cliente | mai | mediana sotto i 10 minuti |
| Spazi con l'assistente collegato a 7 giorni | 0 % | 40 % |
| Spazi attivati a 7 giorni | 0 % | 30 % |
| Tornati almeno una volta a 7 giorni | 25 % (2 su 8, uno interno) | 50 % |

La misura strumentata arriva con PostHog e non è in questa spec. Finché non c'è, i
numeri si leggono con la query di §1; portarli nell'hub è una card di backlog (§7).

## 5. Le regole del nuovo disegno

1. **Una persona, un'identità: l'email.** In PigroCRM si entra come nella community, con
   un link via mail. La password resta possibile per chi la ha già (la radice, i sette
   spazi di oggi, l'e2e), come seconda via sotto il bottone principale; a nessuno viene
   più chiesta.
2. **Registrarsi è entrare.** Chi crea uno spazio si trova dentro, con la sessione
   aperta, senza una seconda porta.
3. **Uno spazio nasce pronto.** Stati di pipeline, template dei documenti e categorie di
   costo predefiniti, per gli spazi nuovi e per quelli che esistono già.
4. **La Home di uno spazio nuovo dice cosa fare**, e la prima cosa che dice è «collega
   il tuo assistente».
5. **L'hub e il CRM restano due prodotti.** Niente importa niente (regola del
   2026-09-09); parlano per API con il segreto che già condividono
   (`PIGROCRM_REGISTRY_TOKEN` = `ORBITERS_PIGRO_REGISTRY_TOKEN`). Ogni spazio resta un
   database che non sa cosa sia un tenant: i token dei link vivono nello spazio, come i
   refresh token.

## 6. Specifiche

### 6.1 La posta del CRM (core)

`pigrocrm.core.mail`, con la stessa forma di `orbiters_core/mail.py`: un `Protocol`
`EmailSender` con `send(mail) -> bool` che non solleva mai, un `ResendSender`, un
`RecordingSender` per i test e per leggere il link in sviluppo, `sender_from_settings`
che risponde `None` senza chiave. Settings nuove: `PIGROCRM_RESEND_API_KEY`,
`PIGROCRM_MAIL_FROM` (default `PigroCRM <ciao@joinorbiters.com>`, stesso dominio con SPF
e DKIM già impostati per l'hub). La cornice HTML è quella dell'hub, con il nome PigroCRM
al posto di Orbiters e i link a privacy e termini del sito. Senza chiave, ogni endpoint
che manderebbe una mail risponde 503 con una frase, come nell'hub. Nessun indirizzo e
nessuna chiave finiscono nei log.

Il codice non si condivide con l'hub per la regola del 2026-09-09: sono ottanta righe, e
la cornice è già diversa per nome e link. Se un giorno divergono davvero, `shared/` è
il posto, non un import.

### 6.2 Il link via mail come login (core, api, web)

**Schema dello spazio**, una migrazione: `users.password_hash` diventa nullable
(`authenticate` rifiuta un utente senza password come rifiuta una password sbagliata,
stessa frase, stesso costo); `users.email_verificata_il` (timestamp, null); una tabella
`magic_link_tokens` (`user_id`, `token_hash`, `expires_at`, `used_at`, `created_at`),
come `MagicLinkToken` nell'hub.

**`MagicLinkService`** in `pigrocrm.core.auth`: `request(email) -> Mail | None` (utente
attivo trovato: spazza i token spesi e scaduti dell'utente, ne crea uno di 15 minuti,
risponde la mail con il link; altrimenti `None`) e `enter(raw) -> UserRead | None` (token
valido e non speso, marcato speso con un `UPDATE … RETURNING` condizionale come nell'hub,
così il prefetch di uno scanner di posta non consuma il click della persona). La prima
entrata con link di un utente scrive `email_verificata_il` e **revoca ogni refresh token
emesso prima** (`RefreshTokenService._revoke_all_valid`, che esiste già): è quello che
rende sicura la sessione aperta alla registrazione (§6.4), perché chi avesse creato uno
spazio con l'email di un altro perde la sessione al primo click del vero titolare.

**API**, in `routers/auth.py`:

- `POST /api/auth/link` con `{email}`. Sotto un prefisso, cerca l'utente nello spazio
  della richiesta e manda il link `/<slug>/app/entra?t=…`. Alla radice senza prefisso,
  chiede al registro gli spazi con quell'`owner_email`, apre ciascuno e manda **una**
  mail con un link per spazio (il caso `mohamed`: due spazi, due link, una mail); nessuno
  spazio → prova la radice stessa (Ivan). Risponde sempre 202, e 503 con una frase senza
  mittente configurato.
- `POST /api/auth/entra` con `{t}`: `enter`, poi gli stessi cookie di `login`, con lo
  stesso `cookie_path`. 401 per un link scaduto o speso, con la frase per la pagina.

**Web.** Il login ha un solo campo, l'email, e il bottone «Mandami il link». Dopo il
202: «Controlla la posta: il link vale 15 minuti». Sotto, in piccolo, «Hai una password?
Accedi con la password» apre il form di oggi. Il bottone «Crea il tuo spazio» resta sulla
radice. La route `/app/entra` legge `t`, chiama `entra`, e naviga alla Home; un 401
mostra la frase e il campo email per chiederne un altro.

Il `PIGROCRM_TOKEN` per l'MCP e i ruoli non cambiano: il link decide chi sei, non cosa
puoi fare.

### 6.3 L'hub risponde chi è membro (hub, api)

Nell'hub, `GET /api/hub/members/lookup?email=…` sotto bearer
`ORBITERS_PIGRO_REGISTRY_TOKEN` (lo stesso segreto della lettura del registro, nell'altra
direzione; 404 della route senza token configurato, 401 con bearer sbagliato, come fa
`GET /api/tenants/` nel CRM). Risponde `{membro: true, nome, cognome}` per un freelancer
con quell'email, `{membro: false}` altrimenti. Mai un errore per un'email sconosciuta.

Nel CRM, `GET /api/tenants/membro?email=…` inoltra la domanda con
`PIGROCRM_REGISTRY_TOKEN` e `PIGROCRM_HUB_URL` (default `https://joinorbiters.com`), e
aggiunge la cosa che solo il registro sa: `spazi: [slug, …]` già intestati a quell'email.
Hub irraggiungibile o senza token → `membro: false`, e la registrazione va avanti lo
stesso: la community è la via veloce, non un cancello.

### 6.4 Il wizard di registrazione (api, web)

Due passi e un atterraggio, in una card con «1 di 2» in alto.

**Passo 1, l'email.** «Con quale email ti conosciamo?» e un campo. Su «Avanti» la pagina
chiama `GET /api/tenants/membro`:

- ha già spazi → la card cambia: «Hai già uno spazio: `pigro.joinorbiters.com/mohamed`.
  Ti mandiamo il link per entrare», un bottone che chiama `POST /api/auth/link`, e sotto
  «Vuoi crearne un altro?» che porta al passo 2. È la fine dei duplicati per sbaglio;
- membro senza spazi → passo 2 con il nome già scritto («Sei dei nostri: ciao Ada»);
- non membro → passo 2 con il nome vuoto e una riga «Non sei ancora nella community?
  Puoi entrare comunque; nella mail ti raccontiamo Orbiters».

**Passo 2, il nome.** «Come si chiama il tuo spazio?» con il nome della persona come
proposta; sotto, in una riga, `pigro.joinorbiters.com/ada-lovelace è libero` e un link
«cambia» che apre il campo dell'indirizzo solo a chi lo vuole, con la verifica di
disponibilità di oggi. Nessuna password. Una riga «Creando lo spazio accetti i termini e
la privacy». Il bottone «Crea lo spazio».

**`POST /api/tenants`** perde `password` (la rifiuta: `extra="forbid"`), crea l'admin senza
password (`UserCreate.password: str | None`, accettato solo da `Actor.system()`), semina i
predefiniti (§6.5), scrive `ragione_sociale = nome` nel profilo emittente, **apre la sessione
dello spazio per la durata di un access token** (il solo cookie di accesso, `path=/<slug>/`,
quindici minuti: è quanto merita un indirizzo che nessuno ha ancora dimostrato), manda la
mail di benvenuto (§6.6) il cui bottone è un link via mail, e risponde 201 con
`Location: /<slug>/app/`. La pagina naviga lì. Il click sul link del benvenuto dimostra
l'indirizzo, apre il refresh token e revoca quanto aperto prima (§6.2). Finché non succede,
un account senza password e senza indirizzo verificato non può creare token personali né
utenti (`require_verified_identity`): chi scrive l'email di un altro lavora quindici minuti e
non tiene nulla. La registrazione è limitata per client come la domanda sul membro.

**Atterraggio.** La Home dello spazio nuovo (§6.7).

### 6.5 Uno spazio nasce pronto, e quelli che esistono si mettono in pari (core, api)

`ensure_defaults(session)` in `pigrocrm.core.tenants`: per ciascuna delle tre famiglie,
**se la tabella è vuota** chiama il `seed_defaults` che già esiste con `Actor.system()`:
`PipelineService`, `TemplateService`, `CostCategoryService`. «Se vuota» e non «sempre»:
chi cancella un template predefinito per fare il suo non lo ritrova al riavvio.

Chiamata in due punti: dentro `provision`, dopo l'admin (un fallimento è un fallimento
del provisioning, `_undo` come per gli altri passi); e dal comando
`pigrocrm ensure-space-defaults`, che scorre il registro e la applica a ogni spazio, eseguito
nel `CMD` di `Dockerfile.api` dopo `alembic upgrade head`, così gli otto spazi di oggi si
mettono in pari al primo avvio dopo il deploy, senza comandi a mano. Non un hook nella
costruzione dell'engine dello spazio in `deps.py`: ORB-170 sta spostando proprio quel registro
in `packages/core`, e un secondo cambiamento sugli stessi file sarebbe un conflitto certo.
La radice non passa di qui: i suoi predefiniti li ha già scelti Ivan.

Il template predefinito è quello che `seed_defaults` semina oggi; ogni spazio lo trova in
Impostazioni → Template e lo modifica come suo, perché è una riga del suo database.

### 6.6 La mail di benvenuto (core, api)

Al 201 di `POST /api/tenants`: oggetto «Il tuo spazio PigroCRM è pronto», il bottone «Entra nel
tuo spazio» che è un link via mail (`/<slug>/app/entra?t=…`, quindici minuti, una volta sola:
il click dimostra l'indirizzo e apre la sessione durevole), il link `/<slug>/app/login` come
«le altre volte si entra con la tua email, ti arriva un link»,
l'assistente in una frase con il link alla pagina che lo collega, i tre primi passi come
frasi (dati fiscali, primo cliente, prima offerta), e per chi non è membro un paragrafo
su Orbiters con il link al wizard. Voce di `docs/design/positioning.md`, cornice di §6.1.
`RecordingSender` nei test afferma destinatario, link e che nulla di sensibile ci finisce.

### 6.7 La Home di uno spazio nuovo (web)

Sopra le tab, due cose, entrambe derivate dai dati e mai salvate.

**La card dell'assistente.** Larga, prima di tutto: «Il CRM che lavora al posto tuo. Collega
Claude al tuo spazio e chiedigli di registrare le ore, preparare un'offerta, riassumere la
settimana». Il bottone «Collega l'assistente» porta alla pagina del collegamento che Ivan
sta facendo in ORB-170: la voce «Collega un agente» della sidebar apre una finestra con
l'indirizzo dell'MCP e il token; il bottone della Home apre la stessa finestra, quindi la card
si fa dopo quella PR. La card resta finché lo spazio non ha almeno un token personale
(`/api/tokens`), poi sparisce: il collegamento è la cosa che vuole ottenere.

**«Primi passi».** Quattro voci, nell'ordine in cui il prodotto le richiede, ciascuna
un link alla pagina giusta e ciascuna «fatta» quando la cosa esiste:

1. **I tuoi dati fiscali** → Impostazioni → Emittente. Fatto con partita IVA o codice
   fiscale salvati.
2. **Il primo cliente** → Clienti, con la creazione aperta.
3. **Il primo deal, o le prime ore** → Deal o Ore.
4. **La prima offerta** → il deal, «Crea documento».

Lo stato viene dai conteggi che le query esistenti già fanno; niente tabella, niente
migrazione. Il pannello sparisce da solo a quattro su quattro; «Nascondi» lo chiude prima e
quella preferenza sta nel browser. Sulla radice non compare, perché la condizione non si
dà.

### 6.8 Il sito non cambia

Ogni bottone di joinorbiters.com manda al wizard della community (ORB-160, ORB-165): il CRM
si raggiunge dalla pagina «Grazie» e dall'area membro, dopo essere entrati. È la porta
community-first che il prodotto vuole, e questa spec la lascia com'è. La prima stesura
proponeva di puntare l'hero di `/pigrocrm` alla registrazione: letta su un checkout
vecchio, era già falsa (ORB-175, annullata).

## 7. Fuori da questa spec

- **Il pulsante che collega l'MCP** e il trasporto remoto: li fa Ivan a parte. §6.7 ci
  punta con una costante.
- **PostHog.** Quando arriva, gli eventi da emettere sono già nominati in §4: registrazione
  iniziata e completata, link chiesto ed entrato, token creato, i quattro primi passi.
- **`GET /api/tenants/{slug}/attivazione` per l'hub.** Utile, non urgente: la query di §1
  basta finché gli spazi sono decine. Card in backlog.
- **Inviti e loop di espansione.** Da discutere quando l'attivazione supera zero.
- **Dati di esempio.** No: finiscono nelle analisi di chi lo usa davvero.

## 8. Decisioni prese qui e da confermare

| Decisione | Scelta | Perché |
|---|---|---|
| Chi non è nella community può creare uno spazio? | Sì. La community è la via veloce (nome già scritto), non un cancello | Un passo in più prima del valore costa più di quanto rende; la mail di benvenuto lo invita nella community |
| Sessione aperta subito alla registrazione, o solo dal link nella mail? | Subito ma breve: il solo access token, quindici minuti, senza refresh, senza token personali né utenti nuovi finché il link del benvenuto non dimostra l'indirizzo; quel click apre la sessione durevole e revoca ogni sessione precedente | Zero porte per chi è onesto; nessun vantaggio duraturo per chi scrive l'email di un altro (revisione di ORB-176: la prima stesura lasciava un refresh di sei mesi e una password) |
| La password sparisce? | Non viene più chiesta a nessuno e la registrazione la rifiuta; resta come seconda via per chi la ha | La radice, i sette spazi e l'e2e continuano a funzionare il giorno del deploy |
| Gli spazi esistenti ricevono i predefiniti? | Sì, al primo avvio dopo il deploy, solo se la tabella è vuota | Sono tutti vuoti; nessun comando a mano, nessun template cancellato che rispunta |

## 9. Ordine e card

| Card | Cosa | Scope | Dipende da |
|---|---|---|---|
| ORB-171 | Uno spazio nasce pronto, e quelli esistenti si mettono in pari (§6.5) | core, api | — |
| ORB-172 | Il CRM manda posta, e si entra con un link via mail (§6.1, §6.2) | core, api, web | — |
| ORB-173 | L'hub dice chi è membro, e il CRM lo chiede (§6.3) | hub, api | — |
| ORB-176 | Il wizard di registrazione apre la sessione e manda il benvenuto (§6.4, §6.6) | api, web | ORB-171, ORB-172, ORB-173 |
| ORB-174 | La Home di uno spazio nuovo: l'assistente e i primi passi (§6.7) | web | ORB-170 (la finestra «Collega un agente») |

ORB-171, ORB-172, ORB-173 e ORB-174 non si toccano nei file e partono insieme; ORB-176 chiude. Progetto Linear: «PigroCRM v2 - a space is born ready, and you enter with your email». Ogni card è una PR
verso `main` (preview); il tag di produzione lo decide Ivan, e con lui la chiave Resend
in `/opt/pigrocrm/.env` e il token dell'hub nell'altra direzione.
