# PigroCRM — Slice 5: Gmail e landing page

**Data:** 2026-08-20
**Stato:** da approvare
**Prerequisiti:** slice 1 in `main`; slice 2 (documenti) per gli allegati; slice 3 (fatture) per i
solleciti. Le dipendenze sono verificate al §3, non assunte.

**Ambito:** l'integrazione Gmail — OAuth, sincronizzazione delle sole conversazioni rilevanti,
invio, solleciti di pagamento — e la landing page pubblica con il sistema visivo soft.

---

## 1. Perché queste due cose stanno nello stesso slice

Sono due prodotti diversi. Non condividono una tabella, un servizio, un test, una riga di codice.
Metterle nella stessa spec richiede una ragione, e la ragione asserita («sono entrambe roba da
slice 5») non basta.

La ragione vera è meccanica, e va in un solo verso.

**Google non concede gli scope Gmail a un'applicazione senza una homepage e una privacy policy
pubbliche.** La schermata di consenso mostra all'utente l'URL della homepage e quello
dell'informativa; la procedura di verifica per gli scope *restricted* — `gmail.readonly` e
`gmail.send` lo sono entrambi — controlla che esistano, che stiano su un dominio verificato e che
descrivano cosa l'applicazione fa con i dati. Finché quelle pagine non esistono, l'OAuth client
resta in stato **Testing**, e in stato Testing **il refresh token di un account Google consumer
scade dopo 7 giorni**.

Quindi:

| | |
|---|---|
| La landing dipende da Gmail? | **No.** In nulla. |
| Gmail dipende dalla landing? | **Sì.** Senza `/`, `/privacy` e `/termini` pubbliche, la connessione Google si rompe ogni settimana per costruzione |

L'ordine corretto è quindi l'opposto di quello intuitivo: **prima la landing, poi Gmail.** La
landing non è la vetrina che si aggiunge quando il prodotto è finito, è un prerequisito tecnico
dell'ultima integrazione del prodotto.

Due precisazioni, perché la dipendenza non è universale:

- Un'installazione self-hosted **può** restare in Testing per sempre, con il proprio Google Cloud
  project e sé stessa come unico test user. In quel caso non serve alcuna verifica — ma si paga la
  riconnessione ogni 7 giorni. Il §5.5 tratta questo caso come *normale*, non come eccezione.
- Un account **Google Workspace** con l'app pubblicata come *Internal* alla propria organizzazione
  non ha né la verifica né la scadenza a 7 giorni. È il caso migliore, ed è quello dell'istanza di
  riferimento.

**Conclusione: un solo slice, due piani.** Il §14 dice quali, e perché tenerli in un unico piano
sarebbe una finzione.

---

## 2. Cosa si porta dal gestionale precedente, e cosa si rifà

Il gestionale precedente manda email da Gmail e manda solleciti già oggi, in produzione. Vale lo stesso criterio
dello slice 2: **il contenuto conquistato si porta, il meccanismo sbagliato si rifà.** Nello slice 2
il contenuto legale dell'offerta è stato portato intatto e la sintassi `[NOME_CLIENTE]` è stata
sostituita, perché uno era materiale scritto e usato per davvero e l'altra era un difetto di
progetto.

| Elemento del gestionale precedente | Decisione | Perché |
|---|---|---|
| **Testo del sollecito e della copia di cortesia** — `buildReminderInvoiceEmailBody` / `buildCourtesyInvoiceEmailBody`, `website/src/App.jsx:2329-2372` | **Portato** | È testo mandato a clienti veri per anni, con la scaletta giusta: numero fattura, data, scadenza, importo, IBAN. Diventa un template `sollecito` del motore dello slice 2, con il livello di sollecito come variabile |
| **La firma** (`Mario Rossi / CTO / mobile / web`), duplicata **verbatim** nei due builder | **Portata la forma, rifatta la sostanza** | Diventa un campo di `emitter_profile` (slice 2 §4.4). Stessa lezione dello slice 2 sull'header Typst: un CRM per freelance italiani non può avere il nome di un freelance nel sorgente — e non due volte |
| Inviare **come l'utente, dalla sua casella** (`COMPANY_EMAIL`, `vite.config.js:29`) | **Portato come principio** | Un'email che arriva da `noreply@` non ottiene risposte. È la decisione giusta, ed è la ragione per cui serve OAuth e non SMTP |
| Chiamata a `POST /gmail/v1/users/me/messages/send` (`vite.config.js:5334`), unica chiamata Gmail di tutto il repo | **Portato l'endpoint** | È quello giusto. Ciò che manca è tutto attorno |
| HTTP grezzo con `fetch`, nessuna libreria client Google (`GOOGLE_TOKEN_URL`, `vite.config.js:23-26`) | **Portato l'approccio** | Coincide con `gdrive.py` dello slice 2. Nessuna dipendenza `googleapis` in nessuno dei due |
| `getGoogleAccessToken` (`vite.config.js:2286-2311`): refresh token da variabile d'ambiente, casella unica per installazione, nessuno stato | **Rifatto** → `google_accounts` (§5.2) | Nessuna revoca, nessuna scadenza, nessuna traccia, nessun per-utente. E il refresh token di Gmail **ripiega su quello di Drive** (`effectiveGmailRefresh`, `vite.config.js:5189`): due capacità diverse su una sola credenziale, che è il difetto che il §5.1 e il §8.4 esistono per non rifare |
| Nessuna cache dell'access token: `expires_in` scartato, 6 punti di chiamata, **due scambi OAuth per una sola email di fattura** (`vite.config.js:5304` e `5314`) | **Rifatto** → cache in-process (§5.2) | Non è un'ottimizzazione: è il motivo per cui un errore transitorio di rete si presenta due volte per ogni invio |
| Gestione errori: `parseGoogleError` + `truncateMessage(400)` → 500 | **Rifatta** (§5.5) | **Non distingue `invalid_grant` da un errore transitorio.** Un token revocato e una rete che fa i capricci producono la stessa schermata, quindi la stessa reazione sbagliata: riprovare |
| `buildRawEmailMessage` (`vite.config.js:2480-2525`): RFC822 `multipart/mixed` a mano | **Rifatta, stessa struttura** | Tre cose mancano e servono: **nessun `Message-ID`** (§6.2), nessun `In-Reply-To`/`References` (quindi il sollecito non si aggancia al thread dell'invio originale), e `Content-Transfer-Encoding: 7bit` dichiarato su corpi italiani che contengono `à` e `’` — **un difetto vivo in produzione**, e la ragione per cui in questo slice il corpo si dichiara `quoted-printable` o `base64`, mai `7bit` |
| Registrazione dell'invio: `emailSentAt` / `emailLastSentAt` / `emailSentCount` / `emailLastSubject` / `emailLastTo` in un JSON su disco (`vite.config.js:5364-5395`) | **Portati i campi, rifatto il supporto** | I campi sono quelli giusti e diventano colonne. Il JSON no: read-modify-write non atomico, quindi due invii concorrenti perdono il conteggio |
| Solleciti | **Rifatti** (§7) | Vedi sotto: è la parte peggiore, ed è la parte che questo slice migliora di più |
| Lettura della posta | **Non c'è nulla da portare** | Verificato: `users/me` compare una volta sola in tutto il repo, ed è `/messages/send`. Zero occorrenze di `messages.list`, `threads`, `history`, `watch`, `labels`, IMAP, SMTP. Tutto il §4 è codice nuovo, senza precedente da cui copiare **né da cui ereditare difetti** |
| Il backend dentro `vite.config.js` (5.485 righe), in produzione servito da `vite preview` | **Non si porta** | Vale la critica dello slice 1 §2.2. Qui pesa il doppio: un client Gmail non testabile è un client Gmail non testato, e **in quel repo non esiste un solo test** |
| Auth: credenziali in chiaro nel sorgente client, **API del tutto non autenticata** (`App.jsx:38-40`) | **Non si porta** | La password nascondeva l'interfaccia, non l'API. Rilevante qui perché lo slice 1 ha già risolto l'autenticazione, e il §8.4 dice cosa resta da fare **prima** di aggiungerci una credenziale Google |

Due difetti del gestionale precedente meritano più di una riga di tabella, perché sono esattamente i due problemi
che il §6.3 e il §7.3 esistono per risolvere — e non sono ipotesi, sono in produzione adesso.

**Uno: l'invio avviene prima della persistenza, e la persistenza può fallire.** `vite.config.js`
manda l'email alla riga 5334, poi cerca su disco il JSON dell'offerta da aggiornare — con una
scansione di tutti i `*.json` e un confronto approssimato sui nomi normalizzati NFKD
(`vite.config.js:5245-5292`). Se il confronto non trova nulla, la risposta è
`404 'Offerta non trovata per registrare l'invio email.'` **mentre l'email è già stata
consegnata.** L'operatore legge un errore e riprova: doppio invio. È letteralmente lo scenario
«il CRM crede una cosa diversa da quella che è successa», e il §6.3 è la risposta.

**Due: il sollecito è solo un corpo diverso, scelto da un booleano.**
`wasSent = emailSentCount > 0` (`App.jsx:2382-2384`) decide fra oggetto
`Invio copia di cortesia – X` e `Sollecito pagamento – X`, e il pulsante diventa «Sollecita». Non
esiste **alcun** controllo: nessuna data di scadenza, nessun intervallo minimo, nessun tetto,
nessun blocco. `emailSentCount` sceglie il template e non impedisce niente; premere il pulsante
dieci volte manda dieci email. E la scelta è sbagliata anche quando funziona: una copia di
cortesia rimandata perché la prima era rimbalzata diventa, al secondo invio, una lettera di
sollecito.

**Il precedente tecnico da seguire non è nel gestionale precedente, è in `packages/core/src/pigrocrm/core/storage/gdrive.py`**
(slice 2, già in albero): chiamate HTTP con `urllib.request`, firma con `pyjwt[crypto]`, nessuna
libreria client Google, e — soprattutto — un *seam* iniettabile (`HttpCall`) che
`packages/core/tests/fakes/fake_drive.py` sostituisce con un finto del **trasporto**, non del
servizio. Il client Gmail di questo slice ha la stessa forma e un `FakeGmail` gemello: costruzione
degli URL, del `q`, del corpo RFC822 e gestione degli errori girano per davvero nei test, perché
sono esattamente le parti che sbagliano — come dimostrano i due difetti qui sopra, entrambi in
codice che nessun test ha mai eseguito.

---

## 3. Cosa questo slice pretende dagli slice precedenti

Da verificare **prima** di pianificare, non da assumere.

| Prerequisito | Da dove | Se manca |
|---|---|---|
| Un'entità fattura con importo, **data di scadenza** e **stato di pagamento** | Slice 3 | I solleciti (§7) non esistono. Non c'è modo di sapere cosa sollecitare. Il resto dello slice non è toccato |
| `document_versions.storage_key` e `DocumentStorage.get` | Slice 2 | Si può inviare, ma senza allegati. L'invio dell'offerta — il caso d'uso che lo slice 2 §10 rimanda esplicitamente qui — non funziona |
| Il motore di template `{{}}` con `#if` | Slice 2, **già in albero** | Corpo dell'email e testo del sollecito diventerebbero stringhe nel sorgente. Non accettabile |
| Una **firma email testuale** nell'`emitter_profile` | Slice 2 §4.4 — ma vedi il §10: l'`emitter_profile` **in corso di implementazione** ha `firma_key`, che è la chiave storage di un'immagine di firma, non un blocco di testo | La firma tornerebbe hardcodata nel sorgente, come nel gestionale precedente, e duplicata in ogni template che la usa |
| **PAT con scope, scadenza e audit trail** | Residui 1A **R10** e **R5**, oggi aperti | Vedi §8.4: è un prerequisito bloccante, non un miglioramento desiderabile |
| Un indice su `customers.email` | **Non esiste** oggi. `people.email` ce l'ha (`people/models.py`), `customers.email` no (`customers/models.py`) | La risoluzione di rilevanza (§4.2) fa una scansione sequenziale su `customers` a ogni messaggio. Da aggiungere in questo slice |

---

## 4. Sincronizzazione: cosa significa «solo le conversazioni rilevanti»

Il modo di fallire da evitare ha un nome: sincronizzare una casella. Una casella contiene le
newsletter, le ricevute di Amazon, i messaggi della scuola dei figli e le conversazioni con i
clienti. Ingerirla tutta e poi filtrare significa che *tutta* è passata dal processo, ed è già una
promessa rotta anche se poi si scarta il 98%.

### 4.1 La regola, in meccanismo

**Ogni chiamata a `users.messages.list` porta un `q` che contiene almeno un indirizzo email noto
al CRM. Una `list` senza `q` è un bug**, e il §13 lo verifica con un test che ispeziona le
richieste ricevute dal trasporto finto — non con una convenzione scritta in un commento.

Concretamente, per account collegato:

1. Il servizio legge l'**anagrafica degli indirizzi**: tutte le `people.email` e le
   `customers.email` non nulle di entità non archiviate.
2. Li raggruppa a blocchi di **20** e per ogni blocco emette
   `q = "(from:a OR to:a OR from:b OR to:b …) after:<epoch>"`. Venti perché il `q` di Gmail ha un
   limite pratico di lunghezza e venti indirizzi con due clausole ciascuno ci stanno con margine;
   la dimensione del blocco è configurabile per poterla correggere senza toccare il codice.
   `after:` prende gli **epoch secondi** del watermark, non una data, perché una data perde le ore
   e obbliga a rileggere sempre un giorno intero.
3. Il watermark si arretra di **24 ore** a ogni ciclo. Sovrapposizione voluta: costa poco ed è ciò
   che assorbe un messaggio arrivato a cavallo di due esecuzioni. È gratuita perché il vincolo di
   unicità del §5.6 rende l'inserimento idempotente.

### 4.2 Chi decide cosa è rilevante

**Il dato, non una persona e non un'euristica.** Un indirizzo è rilevante perché è su una Persona
o su un Cliente nel CRM. Non ci sono regole da configurare, filtri da mantenere, liste di domini
da curare: la lista di indirizzi rilevanti *è* l'anagrafica, e tenerla aggiornata è il lavoro che
si stava già facendo.

La conseguenza è la parte buona: per far comparire una conversazione si aggiunge la persona al
CRM. È l'azione che si voleva compiere comunque.

### 4.3 La risalita al thread, e il suo costo

Quando un messaggio è rilevante, il servizio chiama `users.threads.get` su quel `threadId` e
memorizza **tutti** i messaggi del thread, compresi quelli di indirizzi che il CRM non conosce.

Perché: una conversazione letta a metà è peggio che non letta. Se il cliente scrive, il suo
collega risponde in copia e il cliente conferma, tenere solo il primo e il terzo messaggio
produce un thread che mente. E l'elenco dei partecipanti a un thread è, di per sé, l'informazione
più utile che ne ricaviamo — è come si scopre chi altro decide.

Il costo, detto in chiaro: **è l'unico punto in cui il CRM memorizza messaggi di indirizzi che
nessuno gli ha indicato.** È limitato ai messaggi di quel thread, mai a una query più larga, e i
mittenti sconosciuti così incontrati **non** entrano nell'anagrafica degli indirizzi — altrimenti
la rilevanza si allargherebbe da sola a ogni ciclo, che è esattamente il modo di fallire del §4.

### 4.4 Un thread che diventa rilevante dopo

Tre casi, tutti e tre devono funzionare.

| Caso | Meccanismo |
|---|---|
| Arriva un messaggio nuovo su un thread già rilevante | Il ciclo incrementale lo prende: si interroga per indirizzo, non per thread |
| Si aggiunge un indirizzo al CRM (persona nuova, o email compilata dopo) | **Backfill per quel solo indirizzo**, orizzonte `gmail_backfill_days` (default 90). Registrato come `activities`, quindi visibile |
| Serve tutto lo storico di quel cliente, non 90 giorni | Azione esplicita «sincronizza tutto lo storico», senza orizzonte, **su un solo indirizzo alla volta**, avviata da un umano. Non è un default perché su una casella di dieci anni è lenta e nessuno la vuole per sbaglio |

Il backfill si aggancia al salvataggio dell'indirizzo? **No: si accoda.** `PersonService` non deve
imparare cos'è Gmail — la regola dello slice 1 (`packages/core` non conosce HTTP, i servizi non si
chiamano l'uno dentro l'altro per effetti collaterali di rete) vale qui. Il servizio Gmail
confronta, al ciclo successivo, l'anagrafica degli indirizzi con quelli già visti e tratta i nuovi
come backfill. Un indirizzo nuovo si sincronizza al ciclo successivo, non nell'istante del
salvataggio, e il §11 lo dice all'utente invece di lasciarglielo scoprire.

### 4.5 Quando gira il sync, e come non gira due volte

**Nessun demone.** Il sync parte su richiesta: un pulsante, `POST /api/gmail/sync`, un tool MCP, o
una `docker compose run` da cron installata dall'operatore — lo stesso schema già documentato in
`docker-compose.yml` per il server MCP. Ragione: questo progetto non ha un processo worker, e
aggiungere una coda per un lavoro è complessità che oggi non si ripaga. È lo stesso ragionamento
con cui lo slice 2 ha reso sincrono il render PDF.

Due esecuzioni sovrapposte sono però realistiche (un cron ogni 15 minuti e un umano che preme
il pulsante). Quindi: **advisory lock di Postgres per account** (`pg_try_advisory_lock` su un
intero derivato dall'id dell'account). Chi non ottiene il lock **non aspetta e non fallisce**:
risponde «sincronizzazione già in corso» con l'ora d'inizio. Un utente che preme due volte deve
vedere una risposta, non un errore.

### 4.6 Perché non l'API History e non le notifiche push

| Alternativa | Perché scartata |
|---|---|
| `users.history.list` con `startHistoryId` | Una sola chiamata invece di N, ma restituisce **tutte** le modifiche della casella, da filtrare a valle. La casella passerebbe comunque dal processo: contraddice il §4 per risparmiare chiamate HTTP |
| `users.watch` + Pub/Sub (push) | Richiede un endpoint HTTPS pubblico raggiungibile da Google. Un'installazione self-hosted dietro NAT non può averlo. Il polling è l'unico meccanismo che funziona su **tutte** le installazioni, e un prodotto self-hosted non può avere una funzionalità che dipende dall'essere esposto su internet |

Costo accettato del polling: la latenza. Un messaggio compare nel CRM entro l'intervallo del cron,
non entro un secondo. Per un CRM è irrilevante.

---

## 5. Credenziali Google e modello dati

### 5.1 Scope richiesti, e perché ciascuno

| Scope | Serve per | Perché non se ne può fare a meno |
|---|---|---|
| `openid`, `email` | Sapere **quale** casella è stata collegata (`sub` stabile + indirizzo) | Senza il `sub` non si può rifiutare una riconnessione che punta per sbaglio a un'altra casella, ri-etichettando tutto lo storico |
| `https://www.googleapis.com/auth/gmail.readonly` | La sincronizzazione del §4 | La regola di rilevanza si applica **lato server**, con il `q`. `gmail.metadata` non consente il parametro `q` su `messages.list`, quindi con esso l'unico modo di trovare i messaggi rilevanti sarebbe elencare la casella e filtrare in locale — cioè il modo di fallire del §4. E i corpi (§5.4) non sarebbero leggibili comunque |
| `https://www.googleapis.com/auth/gmail.send` | L'invio del §6 | È lo scope minimo per inviare: non consente di leggere né di modificare nulla |

Scope **deliberatamente non richiesti**, perché chiedere più del necessario in una schermata di
consenso è il modo più rapido di non ottenere il consenso:

| Non richiesto | Cosa consentirebbe | Perché no |
|---|---|---|
| `gmail.modify` | Etichettare, archiviare, spostare | Questo prodotto non tocca la casella. Lo stato vive nel CRM |
| `gmail.compose` | Creare e gestire bozze in Gmail | Le bozze vivono nel CRM (§6.1). Una bozza in Gmail sarebbe un secondo posto dove cercarla |
| `https://mail.google.com/` | Tutto, incluso cancellare | Non c'è alcuna operazione in questo slice che lo richieda |
| Drive, Calendar, Contacts | — | Fuori ambito (§12). Drive nello slice 2 usa un **service account**, non il consenso dell'utente: sono due credenziali distinte e restano distinte |

**Gli scope concessi si registrano, e ogni funzionalità controlla quelli concessi, non quelli
richiesti.** Google può concedere un sottoinsieme.

E la conseguenza è una separazione che va tenuta ferma, perché confonderla produce esattamente la
contraddizione in cui cade il resto delle integrazioni OAuth: **lo stato della credenziale e la
sufficienza degli scope sono due cose diverse.** Una credenziale valida a cui manca uno scope è
sana; è la *funzionalità* che non è disponibile. Quindi `status` (§5.2) descrive solo la
credenziale, e la capacità si deriva da `scopes_granted` al momento dell'uso: se arriva
`gmail.send` ma non `gmail.readonly`, `status` resta `active`, l'invio funziona, e il **sync**
rifiuta con un errore che nomina lo scope mancante e il pulsante «ri-autorizza».

### 5.2 Dove sta il refresh token

Tabella `google_accounts`, una riga per utente CRM.

| Colonna | Note |
|---|---|
| `user_id` | FK `users`, unico. Una casella per utente: due caselle raddoppiano la domanda di rilevanza senza che nessuno l'abbia chiesto |
| `google_sub`, `email_address` | Identità dell'account Google. `google_sub` è ciò su cui si confronta una riconnessione |
| `refresh_token_ciphertext`, `refresh_token_nonce` | **Cifrato a riposo**, AES-GCM, chiave da `PIGROCRM_GOOGLE_TOKEN_KEY` (32 byte, base64). `cryptography` è già in albero via `pyjwt[crypto]` |
| `scopes_granted` | Quelli concessi davvero (§5.1). **Non** entra in `status`: la capacità si deriva da qui, la salute della credenziale da `status` |
| `status` | `active` · `expired` · `revoked`. Tre valori, non quattro: `expired` è ciò che **abbiamo previsto** (la finestra di consenso è passata e non c'è stato un refresh riuscito da allora), `revoked` è ciò che **Google ci ha detto** (`invalid_grant`). Sono reazioni diverse — il primo è un avviso da mostrare prima, il secondo un fatto da registrare — quindi sono due stati |
| `consent_expires_at` | Quando **va rinnovato il consenso**, non quando scade l'access token. Vedi §5.5 |
| `last_error`, `last_error_at` | Il testo che l'utente legge, non lo stack |
| `sync_watermark`, `last_sync_at` | §4.1 |
| `connected_at`, `disconnected_at` | |

**Perché cifrare, se il database è dell'utente stesso.** Non per proteggerlo da sé: perché un dump,
un backup, o un `pg_dump` allegato a una segnalazione sono superfici di esposizione diverse dal
sistema in esecuzione, e questa credenziale dà accesso a un **account di terze parti**, non solo a
questa applicazione. La chiave sta fuori dal database: è tutto il punto. Se
`PIGROCRM_GOOGLE_TOKEN_KEY` manca all'avvio e c'è almeno una riga in `google_accounts`, l'API
**fallisce l'avvio** con un messaggio che lo dice, invece di scoprirlo al primo sync — la stessa
disciplina di `Settings._jwt_secret_must_be_long_enough`.

**Gli access token non si memorizzano mai.** Vivono in memoria per la durata di un sync o di un
invio, con la cache in-process limitata dall'`expires_in` che Google restituisce. Un access token
vale un'ora: persisterlo aggiungerebbe un secondo segreto da proteggere senza alcun guadagno. È
ciò che fa già `gdrive.py`.

### 5.3 Il flusso OAuth

Authorization code con PKCE, lato server.

- `GET /api/gmail/oauth/start` → 302 verso Google con `access_type=offline`, `prompt=consent`
  (senza il quale una riconsegna del consenso **non** restituisce un refresh token nuovo),
  `code_challenge`, e uno `state` firmato: un JWT brevissimo (5 minuti) con un `jti` monouso e il
  `sub` dell'utente CRM, emesso con la macchina già esistente in `auth/tokens.py`. Nessuna
  crittografia nuova.
- `GET /api/gmail/oauth/callback` → verifica `state` (firma, scadenza, `jti` non già consumato) e
  che l'utente della sessione sia quello del `state`. Rifiuta altrimenti, **senza** dire quale
  delle verifiche è saltata.
- Se esiste già una riga `active` con un `google_sub` **diverso**: rifiuta con `Conflict` che nomina
  entrambe le caselle e chiede di scollegare prima. Riconnettere per sbaglio un'altra casella
  ri-etichetterebbe in silenzio tutto lo storico.
- `redirect_uri` = `{PIGROCRM_PUBLIC_URL}/api/gmail/oauth/callback`. Deve essere una sola stringa
  fissa e configurata: Google confronta esattamente.

**Se `PIGROCRM_GOOGLE_CLIENT_ID` non è impostato, Gmail non esiste su quell'installazione**: l'UI
non mostra la sezione, gli endpoint rispondono `Conflict` con «Gmail non è configurato su questa
installazione», i tool MCP non vengono registrati. Assente, non rotto. È ciò che permette a chi
si self-hosta per non avere Google di non avere Google.

### 5.4 Cosa si memorizza e cosa si legge al volo

La posizione, presa e non rimandata: **i corpi si memorizzano, in testo semplice, per default.**

Le tre ragioni:

1. Una timeline di oggetti-email è un indice, non un archivio. Il valore del prodotto è ritrovare
   *cosa* si era detto.
2. Leggere al volo significa che il CRM si svuota **a posteriori**: la corrispondenza di un deal
   chiuso l'anno scorso diventa bianca il giorno in cui il token viene revocato o il messaggio
   viene cancellato da Gmail. Un CRM che perde la memoria del passato quando cambia una credenziale
   non è un CRM.
3. È il database dell'utente, sul server dell'utente. **L'argomento dell'autonomia taglia a
   favore del memorizzare, non contro**: ciò a cui un self-hoster si oppone è che la sua posta
   stia nel SaaS di qualcun altro.

Detto questo, il lavoro di progetto sta nei limiti, non nella scelta:

| Regola | Perché |
|---|---|
| **Solo `text/plain`.** Se il messaggio è solo HTML, si memorizza la conversione testuale e si segna `body_html_scartato` | L'HTML delle email porta pixel di tracciamento, CSS remoto e script. Renderizzarlo farebbe del CRM un beacon e una superficie XSS. Per l'originale c'è «apri in Gmail» |
| Corpo troncato a **256 KB**, con marcatore | Stessa disciplina di `activities/sanitize.py`: un limite generoso che morde solo sull'anomalo |
| **Nessun byte di allegato.** Solo nome, mime, dimensione | Sarebbero gigabyte nello storage dello slice 2. L'allegato che conta si salva con un'azione esplicita: «salva come documento del deal», che passa da `DocumentStorage` e dalla sua autorizzazione |
| Interruttore per account: `gmail_store_bodies = false` | Chi non vuole la corrispondenza nel database ottiene solo intestazioni e lo snippet di Gmail, e la lettura al volo. Con il degrado del punto 2 come conseguenza dichiarata, non nascosta |
| Scollegare l'account **offre** di cancellare i messaggi memorizzati | Non automatico: cancellare la corrispondenza di un deal perché è scaduto un token sarebbe un disastro. La scelta si registra |

### 5.5 Scadenza e revoca: il degrado deve vedersi

Questo è il punto in cui un'integrazione OAuth di solito mente. Le regole:

- Un `invalid_grant` sul refresh è **terminale**. `status = 'revoked'`, `last_error` valorizzato,
  stop. **Non si ritenta**: ritentare un `invalid_grant` è un bug, non riuscirà mai. E non si salta
  in silenzio.
- Si scrive un `activities`: `entity_type='google_account'`, `kind='gmail.credenziale_revocata'`,
  `actor_type='system'`. `entity_type` era un valore aperto per progetto (slice 1 §5.8) e
  `sanitize_payload` documenta nel proprio docstring l'oggetto di un'email come esempio: il punto
  di estensione era stato disegnato per questo.
- L'app mostra un **banner persistente nella shell**, non un toast. Un toast che scorre via è un
  fallimento silenzioso con passaggi in più.
- **Ogni invio verso un account non `active` fallisce prima di comporre il messaggio**, con un
  `Conflict` che nomina l'account e la ragione. L'umano lo scopre quando preme Invia, non
  dopo.
- I tool MCP restituiscono la stessa diagnosi in forma di frase (§8.2 della spec di slice 1).
- **`/health` non cambia.** Una credenziale Gmail rotta non è un deploy rotto, e confonderle
  addestra l'operatore a ignorare `/health`.

E il caso che in Testing è la normalità, non l'eccezione: `consent_expires_at` viene valorizzato a
`connected_at + 7 giorni` quando l'app è in Testing (impostazione dichiarata dall'operatore,
`PIGROCRM_GOOGLE_APP_UNVERIFIED=true`, perché Google non lo espone via API). L'UI avvisa **a 48
ore dalla scadenza**, cioè *prima* che qualcosa fallisca. Un avviso dopo il primo errore è un
avviso inutile: l'errore era già l'avviso.

### 5.6 Il modello dati completo

Sei tabelle nuove. Valgono le convenzioni dello slice 1: `id` UUID v7, `created_at`/`updated_at`,
`timestamptz` in UTC, soft delete dove ha senso.

| Tabella | Colonne che contano | Vincoli |
|---|---|---|
| `google_accounts` | §5.2 | `user_id` unico |
| `google_oauth_states` | `jti`, `code_verifier`, `user_id`, `expires_at`, `consumed_at` | `jti` unico. Esiste perché **il `code_verifier` di PKCE deve stare lato server** fra `/start` e `/callback`: metterlo nello `state` firmato lo renderebbe leggibile dal browser e annullerebbe PKCE. È anche il registro che rende il `jti` monouso per davvero, invece di per modo di dire. Le righe scadute si potano al ciclo di sync — a differenza di `refresh_tokens`, che secondo il residuo **R8** non le pota affatto |
| `gmail_messages` | `google_account_id`, `gmail_message_id`, `gmail_thread_id`, `message_id_header`, `in_reply_to`, `references`, `direction` (`inbound`/`outbound`), `from_address`, `to_addresses`, `cc_addresses`, `subject`, `snippet`, `internal_date`, `body_text`, `body_truncated`, `body_html_scartato`, `attachments` (JSONB: nome, mime, dimensione) | **`(google_account_id, gmail_message_id)` unico** — è ciò che rende gratuita la sovrapposizione del watermark (§4.1) e idempotente ogni riesecuzione. Indice su `(gmail_thread_id, internal_date)` per il raggruppamento in thread |
| `gmail_message_links` | `gmail_message_id`, `entity_type`, `entity_id` | Unico sulla terna. **Molti-a-molti e non una tripletta di FK nullable**: una sola email riguarda insieme la persona, il suo cliente e un deal, e una FK singola costringerebbe a una scelta che il dato non sostiene |
| `email_drafts` | `entity_type`/`entity_id`, destinatari, `subject`, `body_markdown`, allegati come `document_version_id[]`, `message_id_header` (generato prima dell'invio, §6.2), `send_state`, `send_attempted_at`, `last_error`, `payment_reminder_id` nullable | `send_state` ∈ `bozza`·`in_invio`·`inviato`·`incerto`·`fallito` |
| `payment_reminders` | `invoice_id`, `sequence`, `sent_at`, `email_draft_id` | **`(invoice_id, sequence)` unico** (§7.3) |

Nuovi `kind` di `activities`, tutti senza migrazione perché `entity_type` e `kind` erano valori
aperti per progetto (slice 1 §5.8):

`gmail.account_collegato` · `gmail.account_scollegato` · `gmail.credenziale_revocata` ·
`gmail.sync_eseguito` · `gmail.backfill_eseguito` · `gmail.messaggio_ricevuto` ·
`gmail.messaggio_inviato` · `gmail.invio_incerto` · `gmail.sollecito_inviato`

Le voci sull'account usano `entity_type='google_account'`; quelle sui messaggi usano l'entità
collegata, così l'email compare nella timeline del cliente e del deal.

Una nota che vale la pena mettere per iscritto: `activities/sanitize.py` cita **nel proprio
docstring** «recording, say, an inbound email's subject line» come esempio del perché un payload si
sanifica invece di validarlo. Il punto di estensione non è stato adattato a questo slice — era
stato scritto pensandoci.

---

## 6. Invio

Un'email inviata dal CRM parte **come l'utente, dalla sua casella**, via `users.messages.send`.

### 6.1 La bozza è durevole, e viene prima

`email_drafts` — destinatari, oggetto, corpo Markdown, allegati come
`document_version_id`, entità collegata, `send_state`.

**La bozza si scrive nel database prima di chiamare Gmail.** Perdere un'email scritta a mano per un
errore HTTP è imperdonabile, e un composer che tiene il testo solo nello stato di React lo perde
al primo refresh.

`send_state`: `bozza` → `in_invio` → `inviato` | `fallito` | **`incerto`**.

Il servizio rifiuta di inviare una bozza il cui stato è già `inviato`, `in_invio` o `incerto`
(`Conflict`). Un doppio click, o una richiesta ritentata da un proxy, non possono spedire due
volte.

### 6.2 Cosa registra il CRM

| Cosa | Quando |
|---|---|
| `gmail_messages` con `direction='outbound'`, `gmail_message_id` e `gmail_thread_id` | **Dopo** che Gmail ha risposto. Mai prima |
| `activities` `kind='gmail.messaggio_inviato'` sull'entità collegata | Nella stessa transazione |
| Il `Message-ID` che **abbiamo generato noi** e messo nell'RFC822 inviato | Prima della chiamata |

Quel `Message-ID` nostro serve a due cose, ed è la decisione tecnica centrale di questa sezione:
rende il thread corretto quando il cliente risponde, e rende la riconciliazione del §6.3
**esatta** invece che euristica.

Tre regole sulla costruzione dell'RFC822, tutte e tre imparate dai difetti del gestionale precedente elencati al §2:

1. **`Message-ID` sempre presente**, generato da noi, con la parte a destra della `@` derivata dal
   dominio configurato.
2. **`In-Reply-To` e `References` valorizzati** quando si risponde o si sollecita dentro un thread
   esistente. Senza, il sollecito arriva al cliente come un messaggio slegato: chi lo riceve non
   vede la fattura sopra, e il primo effetto è che chiede di rimandarla.
3. **Il corpo si dichiara `quoted-printable` o `base64`, con `charset="UTF-8"`. Mai `7bit`.** Il gestionale precedente
   dichiara `7bit` su testo che contiene `à` e `’`; funziona per caso, fino al primo client di posta
   che prende la dichiarazione alla lettera. Un test invia un corpo con accenti, virgolette
   tipografiche ed emoji e verifica che l'RFC822 prodotto si ri-decodifichi identico.

### 6.3 Quando l'invio fallisce dopo che il CRM crede che sia riuscito

Due fallimenti diversi, che troppo spesso vengono trattati come uno.

**(a) Gmail ha rifiutato.** Caso pulito: nulla è partito, `send_state='fallito'`, la bozza resta
intatta con l'errore accanto, il composer si riapre con il testo dentro.

**(b) Non sappiamo.** Timeout, connessione caduta, risposta persa — oppure, come nel gestionale precedente oggi,
Gmail ha accettato e **la scrittura successiva è fallita** (§2: `404 'Offerta non trovata per
registrare l'invio email.'` con l'email già consegnata). Il messaggio **può** essere nella cartella
Inviati dell'utente. Non si assume né l'una né l'altra cosa:

1. `send_state='incerto'`. **L'interfaccia non scrive «inviata»**: scrive «esito da verificare»,
   con il pulsante «verifica».
2. La riconciliazione cerca il messaggio con `users.messages.list` e
   `q = rfc822msgid:<il nostro Message-ID>`. Trovato → `inviato`, si adotta l'id di Gmail. Non
   trovato dopo una finestra di grazia di **15 minuti** → `fallito`, bozza intatta.
3. La riconciliazione gira all'inizio di ogni sync e su richiesta.

**Verifica da fare nel primo task dell'invio, non da assumere:** che Gmail conservi il
`Message-ID` fornito dal client su `messages.send`. Se non lo conserva, il ripiego è il confronto
su destinatario + oggetto + `internalDate` entro la finestra di grazia, dentro la sweep per
indirizzo che il §4 fa già. È dichiaratamente inferiore — è un confronto approssimato — e per
questo la via del `Message-ID` è quella da usare se regge.

### 6.4 Allegati

Solo da `document_version_id` dello slice 2. Nessun upload arbitrario dal composer.

Perché: la cosa che si vuole allegare è il PDF dell'offerta — lo slice 2 §10 rimanda esplicitamente
qui l'invio dell'offerta — e passare dal documento significa passare dallo strato che ha già
l'autorizzazione, l'hash e il versioning. Un upload libero nel composer sarebbe un secondo
percorso per far entrare byte nel sistema, con una seconda autorizzazione da scrivere.

Limite: **totale allegati 20 MB**, controllato prima di comporre, con un errore che dice quanto
pesa e quanto è il limite. Gmail rifiuta oltre i 25 MB e un rifiuto di Gmail a metà upload è un
messaggio incomprensibile.

---

## 7. Solleciti di pagamento

Prerequisito al §3: senza uno stato di pagamento sulla fattura non c'è nulla da sollecitare.

### 7.1 Cosa fa scattare un sollecito

Una query, non un evento: `SollecitiService.candidates()` restituisce le fatture con

- stato **non pagata**, **e**
- `data_scadenza < oggi - grace_days` (default 7 — sollecitare il giorno dopo la scadenza è
  aggressivo e spesso sbagliato: il bonifico è già partito), **e**
- nessun sollecito per quella fattura negli ultimi `min_interval_days` (default 14), **e**
- meno di `max_reminders` solleciti già inviati per quella fattura (default 3).

**Questa chiamata non manda niente.** Prepara la lista.

Il confronto con il gestionale precedente è la giustificazione di ognuna delle quattro condizioni: là il sollecito è
scelto da `emailSentCount > 0`, cioè «è la seconda email», senza guardare né la scadenza né
l'intervallo né un tetto (§2). Qui la scadenza è l'unica cosa che rende un sollecito legittimo,
l'intervallo è l'unica cosa che lo rende sopportabile, e il tetto — `max_reminders`, default 3 —
è ciò che impedisce a una fattura contestata di diventare una persecuzione automatica.

**E c'è un segnale che il gestionale precedente non poteva avere.** Da quando il CRM legge la posta (§4), la lista
delle candidate può dire *«il cliente ha risposto il 12 agosto»*, mostrando l'ultimo messaggio in
entrata da quel cliente dopo la data della fattura. Non sopprime la candidata — una risposta non è
un pagamento, e a volte la risposta è proprio ciò che va sollecitato — ma la mette in fondo alla
lista e lo scrive accanto. È il guadagno che si ottiene mettendo la sincronizzazione e i solleciti
nella stessa metà dello slice (§14: entrambi in 5B): **sollecitare chi ti ha già risposto è
l'errore che un CRM che non legge la posta non può nemmeno accorgersi di fare.**

### 7.2 Serve un umano? Sì, sempre, in questo slice

L'utente vede la lista, sceglie, vede l'anteprima del testo — un template `sollecito` del motore
dello slice 2, quindi le parole sono le sue — e preme Invia. **Una pressione, un'email.**

Perché non automatico: un sollecito è un atto commerciale con una relazione dietro. Un cron che ne
manda uno il giorno dopo che al telefono si era concordato un piano di pagamento fa un danno che
nessun risparmio di tempo ripaga. E il criterio del prodotto — *fa risparmiare tempo ogni
settimana?* — è soddisfatto comunque: la parte noiosa è **costruire la lista** incrociando
scadenze e pagamenti, non premere un pulsante.

Cosa dovrebbe esistere perché diventi automatico, se un giorno lo si volesse: un opt-in per
cliente, un registro delle esecuzioni a vuoto consultabile, e un interruttore di spegnimento
immediato. Non esistono, quindi non è automatico.

### 7.3 Come non parte due volte

Tre strati, ognuno con la sua ragione:

| Strato | Cosa impedisce |
|---|---|
| `payment_reminders` con unico su `(invoice_id, sequence)` | Due scritture concorrenti: la seconda prende un `IntegrityError` e diventa `Conflict`. È il database a garantirlo, non il codice applicativo |
| `candidates()` esclude chi ha un sollecito entro `min_interval_days` | Il doppio invio a distanza di ore, dopo che il primo è stato dimenticato |
| Il percorso di invio è quello idempotente del §6.1 | Il doppio click e la richiesta ritentata |

Il tono della sequenza (primo, secondo, terzo sollecito) è una **variabile del template**, non tre
template. Tre template che si somigliano divergono — è la stessa decisione con cui lo slice 2 ha
rifiutato di duplicare i template dell'offerta.

---

## 8. Superficie MCP

La regola non negoziabile resta: **i tool MCP e i router FastAPI chiamano gli stessi servizi**,
in-process, e il test di architettura lo verifica.

Ma un agente che legge una casella e manda posta come te è una proposta diversa da uno che crea un
cliente. Quindi la superficie non è simmetrica, e l'asimmetria è il progetto.

### 8.1 Cosa un agente può fare

| Tool | Perché è concesso |
|---|---|
| `list_gmail_messages(entity_type, entity_id)` · `get_gmail_message(id)` | Leggono ciò che è **già** nel CRM. Un agente può già leggere la timeline con `get_timeline`: non è una superficie nuova |
| `sync_gmail()` · `backfill_gmail(entity_type, entity_id)` | Legge la casella, ma **solo** sotto la regola del §4, e il risultato finisce nel CRM dove è ispezionabile. Registrato in `activities` con `actor_type='mcp'` |
| `draft_email(...)` | Crea una **bozza locale**. È il punto in cui un agente vale di più: «prepara la mail di accompagnamento all'offerta» |
| `list_payment_reminder_candidates()` | Sola lettura |
| `describe_gmail_account()` | Stato della connessione, così l'agente diagnostica invece di ritentare |

### 8.2 Cosa un agente non può fare, e perché

| Non esposto | Ragione |
|---|---|
| **`send_email`** | Un'email inviata dalla tua casella non si richiama, il cliente la legge come tue parole, e un agente con *lettura* della posta e *invio* nella stessa cintura ha la sorgente dell'injection e il canale di esfiltrazione **nello stesso canale**. L'umano preme Invia; l'agente scrive la bozza |
| **`send_payment_reminder`** | Come sopra, con dei soldi in mezzo |
| **`connect_google_account` / `disconnect_google_account`** | Il consenso OAuth è un atto umano per costruzione. Un tool che lo automatizza sta automatizzando la parte che esiste per non essere automatica |
| **Qualunque tool che accetti un `q` Gmail**, o che legga un messaggio non ancora sincronizzato | Altrimenti tutte le garanzie del §4 distano un prompt dall'essere nulle. **Nessun tool di questo slice accetta una stringa di ricerca Gmail** |
| Cancellazione di messaggi sincronizzati | Coerente con lo slice 1: l'MCP non espone delete distruttivi |

### 8.3 La superficie REST

```
GET    /api/gmail/account                        # stato, scope concessi, scadenza consenso
GET    /api/gmail/oauth/start   · /callback
DELETE /api/gmail/account                        # scollega, con la scelta sui dati memorizzati
POST   /api/gmail/sync                           # ciclo incrementale su tutti gli indirizzi
POST   /api/gmail/backfill                       # body: {entity_type, entity_id, full: bool}
                                                 #   full=false -> gmail_backfill_days; true -> tutto
GET    /api/gmail/messages                       # filtrati per entità
CRUD   /api/email-drafts
POST   /api/email-drafts/{id}/send  · /reconcile
GET    /api/payment-reminders/candidates
POST   /api/payment-reminders                    # crea sollecito + bozza da una candidata; NON invia
```

Due precisazioni sulla forma di questa lista, perché è dove sta il progetto:

- `POST /api/email-drafts/{id}/send` esiste come endpoint REST **e non** come tool MCP: è
  esattamente lo scarto fra le due superfici, ed è deliberato. Non è una dimenticanza da colmare in
  un secondo momento.
- `POST /api/payment-reminders` **non invia**: crea la riga `payment_reminders` e la bozza
  corrispondente. L'invio passa da `/api/email-drafts/{id}/send`, come qualunque altra email. È così
  che il §7.3 può contare sull'idempotenza del §6.1 invece di riscriverla: **un solo percorso di
  invio in tutto lo slice.**

### 8.4 Il problema della seconda credenziale, che va chiuso prima

I residui 1A dicono due cose che questo slice non può ignorare:

- **R10**: i PAT non hanno scope, ereditano il ruolo pieno del proprietario e non scadono. «Dai un
  token a Claude» oggi significa «dai il tuo account, per sempre».
- **R5**: creazione e revoca di un PAT non lasciano traccia in `activities`.

Questo slice aggiunge una **seconda credenziale, più potente della prima**: un refresh token
Google che dà accesso a un account di terze parti. Se resta com'è, un PAT emesso per «fai leggere
a Claude i miei deal» legge anche la casella di posta, e nessuno ne sa niente.

**Prerequisito bloccante per la metà Gmail** (minimo indispensabile, non la soluzione completa di
R10):

1. I PAT hanno un insieme di **scope**. Gli scope `gmail:*` **non** sono nel set di default e vanno
   selezionati esplicitamente alla creazione.
2. I PAT hanno un `expires_at` opzionale, **obbligatorio** se il token porta uno scope `gmail:*`
   (default 90 giorni). L'asimmetria ha una ragione: la credenziale che apre la posta è quella per
   cui la scadenza vale il fastidio.
3. Creazione e revoca di un PAT scrivono un `activities`. Chiude R5 per la sola famiglia dei token
   — che è la famiglia per cui era stato segnalato.

Non è un miglioramento desiderabile: è la condizione perché la metà Gmail non peggiori un problema
noto e aperto.

---

## 9. La landing page

### 9.1 A cosa serve, dato che non esiste una registrazione pubblica

Senza signup una landing non converte. «Hero section» è una forma, non uno scopo. Gli scopi, in
ordine di quanto sono vincolanti:

1. **Essere l'homepage e l'informativa privacy della schermata di consenso Google.** È il §1: è
   l'unico scopo *meccanico*, e l'unico che se manca rompe un'altra parte del prodotto. Consegna
   concreta: `/`, `/privacy`, `/termini`, statiche, che **nominano gli scope Gmail richiesti e
   dicono cosa il prodotto fa con i dati**. È la sola pagina del prodotto con una funzione legale.
2. **Dire a chi arriva dal README o da un passaparola cos'è questa cosa in quindici secondi**, e
   se è per lui: freelance o piccola società di consulenza, in Italia, regime forfettario,
   self-hosted, AI-first.
3. **Mandarlo all'unica azione che esiste davvero**: installarlo sul proprio server. La CTA è
   *«Installala sul tuo server»*, non *«Prova gratis»*. Una CTA che promette una registrazione
   inesistente è peggio di nessuna CTA.
4. **Essere la porta d'ingresso di un'installazione esistente.** Chi apre la radice della *propria*
   istanza non deve trovarsi bloccato su del testo pubblicitario: un link «Accedi» discreto, in
   alto a destra, verso `/app`. È un requisito reale del mettere la landing su `/`, allo stesso
   origin dell'applicazione.

Non è uno scopo: raccogliere email, misurare le visite, mostrare loghi di clienti inventati.

### 9.2 Cosa si porta dal `website/` del gestionale precedente — e la correzione necessaria

Prima di progettare, una correzione di fatto, perché cambia cosa c'è da studiare:
**`.reference-*/website/` non è una landing page.** È l'intera applicazione del gestionale precedente — una SPA
React di un solo file (`src/App.jsx`, 6.784 righe, sette tab, nessun router) più il backend dentro
`vite.config.js`. **In quel repository non esiste alcun sito di presentazione**: zero occorrenze di
`hero`, `pricing`, `testimonial`, `signup`, nessun form di contatto, nessun link esterno tranne
`example.com` dentro il testo della firma dell'email.

Quindi dal `website/` **non si porta nessun contenuto**. Si porta della **tecnica**, e sono cose
buone che sarebbe stupido reinventare — mentre la palette e i caratteri non si portano affatto,
perché sono un altro sistema visivo (crema `#f4efe4`, inchiostro verde-nero `#1c241e`, arancio
bruciato `#e36c34`, Fraunces + Space Grotesk + Space Mono) e PigroCRM ha già il suo, con i test
dietro.

| Da `website/` | Decisione |
|---|---|
| **Le due sfumature di fondo sovrapposte** — tre blooms radiali + una tratteggiatura diagonale a 120°, `1px` ogni `10px`, nero al 4% con `opacity .12` (`src/App.css:50-73`) | **Portata la tecnica, ri-tinta.** Vedi il §9.3 (riga «Grana»): è meglio di un `feTurbulence` in `data:` URI perché **costa zero byte** e non aggiunge un asset |
| `@keyframes rise` — `opacity 0→1` + `translateY(12px)→0`, con `@media (prefers-reduced-motion: reduce)` che la annulla (`App.css:1233-1241, 1289-1297`) | **Portata.** È esattamente il movimento giusto e la guardia giusta. Si riduce la durata da `0.6s` a `320ms`: su una pagina che si scorre, `0.6s` per elemento si accumula |
| Pillole `999px` per tutto ciò che è interattivo, `24px` per i contenitori, `12-16px` per i campi | **Portata la gerarchia**, mappata sulla scala di `tokens.css` (§9.3) |
| Ombre grandi, morbide, a bassa opacità, con un `inset 0 1px 0 rgba(255,255,255,.8)` come bordo-luce | **Portate.** È il modo in cui quel sistema ottiene il rilievo senza bordi, ed è ciò che serve qui |
| Superfici bianche translucide all'85% | **Portate**, ma **senza `backdrop-filter: blur(12px)`**: costa GPU su un telefono e su una pagina statica non c'è nulla dietro che valga la pena sfocare |
| Etichette-sopratitolo: `uppercase`, `letter-spacing: .24em`, `.75rem` (`App.css:83-89`) | **Portata.** Un dettaglio piccolo che fa molto del carattere «soft» di quel sistema |
| Tipografia fluida con `clamp()` (`App.css:96-101`) | **Portata** |
| **Google Fonts da CDN** — e caricato **due volte**, con due set diversi di famiglie di cui uno mai usato (`index.html:11-16` e `src/index.css:1`) | **Non si porta.** `tokens.css` documenta già per esteso perché: un prodotto venduto sulla promessa del self-hosting non può consegnare a Google l'IP di ogni visitatore, né rompersi in un'installazione offline. E un `@import` dentro il CSS blocca il rendering |
| `<title>` e `<meta name="description">` **di un altro prodotto** — «Studio Rossi is the AI optimization platform…» (`index.html:7-17`) | **Trappola da nominare, non da portare.** È l'artefatto più simile a una landing in tutto il repo, ed è copia sbagliata rimasta dallo scaffold. La landing di questo slice ha `title`, `description` e Open Graph propri, e il §13 li verifica |

### 9.3 Da dove viene il soft, concretamente

Vincolo: **restare dentro la palette e il carattere già spediti.** `tokens.css` è la fonte unica
del colore e ha dei test dietro. La landing lo **estende**, non lo forka.

**Nessuna tinta nuova.** Il soft si ottiene desaturando e schiarendo le cinque esistenti, per
costruzione:

```css
/* landing.css — importa gli stessi @theme di tokens.css, aggiunge solo --landing-* */
--landing-surface:    color-mix(in oklab, var(--color-mint-cream)   92%, #ffffff);
--landing-veil-warm:  color-mix(in oklab, var(--color-watermelon)   32%, #ffffff);
--landing-veil-gold:  color-mix(in oklab, var(--color-royal-gold)   28%, #ffffff);
--landing-ink:        var(--color-prussian-blue);
--landing-ink-quiet:  var(--color-charcoal-blue);
```

`--landing-veil-warm` al 32% cade nell'intorno del Coral `#FFB7B2` del sistema originale — che
diventa così un **bersaglio da centrare**, non un sesto token da aggiungere. Un test lo verifica
per ΔE, e verifica che **nel blocco `--landing-*` non compaia alcun esadecimale grezzo**: ogni
colore della landing è un `var(--color-…)` o un `color-mix()` di uno. Il fork diventa
meccanicamente impossibile, non sconsigliato.

| Dimensione | Regola |
|---|---|
| **Superfici** | Nessun bordo. L'app separa con `--border` dappertutto; la landing separa con la tinta della superficie e con lo spazio. Default `border-width: 0`; qualunque linea visibile è un capello da `1px` in `color-mix(…, transparent)`, mai `--border`. Il rilievo viene dalle ombre del gestionale precedente (§9.2) — grandi, morbide, a bassa opacità, in Prussian Blue trasparente — più il bordo-luce `inset 0 1px 0 rgba(255,255,255,.8)`. Bianco translucido all'85%, **senza `backdrop-filter`** |
| **Grana** | La tecnica del gestionale precedente (§9.2), ri-tinta: due pseudo-elementi sovrapposti, sotto il contenuto. Il primo, tre blooms radiali in `--landing-veil-warm` / `--landing-veil-gold` / `--landing-surface`; il secondo, una `repeating-linear-gradient` a 120°, `1px` ogni `10px`, `rgba(1,25,54,.04)` — cioè Prussian Blue, non nero — con `opacity .12` e `pointer-events: none`. **Zero byte, zero richieste, nessun asset binario**, che è il motivo per cui questa vince su un `feTurbulence` in `data:` URI. **Spenta sotto `@media (prefers-contrast: more)`**: la trama sta sopra il testo, e sopra il testo è contrasto in meno |
| **Raggi** | Solo `--radius-2xl` e superiori della scala già spedita per i contenitori, `--radius-md`/`lg` per i campi, e `--landing-radius-pill: 999px` per la CTA. È la gerarchia a tre livelli del gestionale precedente mappata sulla scala di `tokens.css`, non una scala nuova |
| **Spazio** | Ritmo più largo di quello dell'app: padding verticale di sezione `clamp(4rem, 10vw, 9rem)`, misura del testo `62ch`. La calma viene dallo spazio, ed è la cosa più economica da azzeccare |
| **Movimento** | Il `rise` del gestionale precedente, accorciato: `IntersectionObserver` che aggiunge una classe, `opacity` + `translateY(12px)`, **`320ms`** invece di `0.6s`, `cubic-bezier(.2,.7,.2,1)`, sfalsamento `60ms`. **Nessun parallasse, nessuna trasformazione legata allo scroll**: combattono con chi legge e su un telefono costano. Tutto dentro `@media (prefers-reduced-motion: reduce)` che le annulla — la guardia c'era già nel gestionale precedente e si porta |
| **Movimento, la regola che conta** | Lo stato iniziale è **visibile**; è lo script ad applicare lo stato nascosto e poi a rimuoverlo. Il contrario — CSS che nasconde, JS che rivela — dà una pagina bianca quando lo script non parte |
| **Carattere** | `Outfit` e nient'altro, dal **medesimo** woff2 già in `apps/web/src/assets/fonts/`, servito dal proprio origin. Riusato, non ri-aggiunto, e mai da CDN (§9.2). Tipografia fluida con `clamp()`; sopratitoli `uppercase` a `letter-spacing: .24em` / `.75rem`, portati dal gestionale precedente |
| **Watermelon** | Solo sulla CTA e sull'anello di focus. E sulla CTA è `--color-watermelon-strong`, non `--color-watermelon`: è precisamente ciò per cui la variante accessibile esiste |

**`Reenie Beanie` resta assente**, e ora con una ragione argomentata invece di un rinvio: un
secondo webfont costa un'altra richiesta e un'altra verifica di licenza, non è leggibile in corpo
piccolo, e un accento manoscritto su una pagina il cui compito è in parte **legale** — è
l'informativa che Google leggerà in verifica — si legge come poco serio. Dove il sistema originale
voleva un accento a mano, si usa `Outfit` 300 in corpo grande con spaziatura generosa.

Conseguenza da gestire, non da nascondere: il test
`does not load Reenie Beanie, which belongs to the landing page` in
`apps/web/src/styles/tokens.test.ts` **va aggiornato**. Il suo assert resta giusto per
`tokens.css`, ma il suo nome afferma ora una cosa falsa — che quel font appartenga alla landing.
Va riscritto come «nessun webfont oltre a Outfit, in nessuno dei due fogli».

### 9.4 Come si serve e come si costruisce

Il requisito: **la landing non deve trascinarsi dietro React, TanStack Router, Radix, dnd-kit e
TanStack Query.**

Decisione: **stesso origin, build separata.** HTML statico, un CSS, uno script da circa un
kilobyte. Nessun framework.

- `apps/web/landing/{index,privacy,termini}.html` + `landing/landing.css` + `landing/reveal.js`
- `apps/web/vite.landing.config.ts`, con quei tre HTML come `rollupOptions.input` e
  `outDir: dist-landing`. Il woff2 di Outfit viene copiato dalla stessa sorgente dell'app: un solo
  file di font nel repository, due build che lo referenziano.
- `Dockerfile.web` esegue le due build e copia `dist-landing` nella radice di
  `/usr/share/nginx/html` e `dist` in `/usr/share/nginx/html/app/`.

Stesso origin e non un sottodominio: un solo certificato TLS, un solo nginx, un solo deploy, e il
link «Accedi» che funziona senza porsi domande cross-origin. Ciò che va separato è il **bundle**,
non l'origine.

**Modifiche necessarie all'app già spedita** (§10 le riassume come contraddizioni da risolvere):

```nginx
location = /            { try_files /index.html =404; }        # landing
location = /privacy     { try_files /privacy.html =404; }
location = /termini     { try_files /termini.html =404; }
location = /app         { return 302 /app/; }                  # senza questa, /app non entra in ^~ /app/
location ^~ /app/       { try_files $uri /app/index.html; }    # SPA
location = /login       { return 302 /app/login; }             # i vecchi link non muoiono
```

- `apps/web/vite.config.ts` prende `base: '/app/'`.
- La rotta `/login` si sposta sotto `/app`.
- `apps/web/src/routes/index.tsx` — che oggi fa `redirect({ to: '/app' })` — **si cancella**: quel
  percorso adesso appartiene alla landing.
- `playwright.config.ts` e gli spec E2E vanno aggiornati ai nuovi percorsi.

Budget, come criterio eseguibile e non come aspirazione: **meno di 40 KB trasferiti** a freddo,
escluso il woff2 condiviso, e **zero richieste verso host diversi dal proprio origin**. Il secondo
numero è ciò che rende «nessun analytics, nessuno script di terze parti» una verifica invece di
una promessa.

---

## 10. Contraddizioni con il codice già spedito

Da risolvere consapevolmente prima di pianificare, non da scoprire implementando.

| Cosa | Dove | Perché è una contraddizione |
|---|---|---|
| `/` reindirizza a `/app` | `apps/web/src/routes/index.tsx` | La landing vuole `/`. Il file va cancellato, non modificato |
| Lo SPA è servito dalla radice con `try_files … /index.html` | `deploy/nginx/spa.conf` | Con la landing in radice quel fallback intercetterebbe `/`. Serve la forma del §9.4, e l'app serve con `base: '/app/'` |
| Il test dice che `Reenie Beanie` «appartiene alla landing page» | `apps/web/src/styles/tokens.test.ts:67` | Questo slice decide che non appartiene a nessuna delle due. Il test resta, il suo nome e il suo commento no |
| `--sidebar-primary` è ancora `--color-watermelon`, con il deficit di 4,22:1 | `tokens.css`, in entrambi i temi | Il commento dice «puntalo a `-strong` quando qualcosa lo usa davvero». La landing non usa la sidebar, quindi non lo tocca — ma va detto che resta aperto, per non riscoprirlo a freddo |
| `customers.email` non è indicizzata, `people.email` sì | `customers/models.py` vs `people/models.py` | Il §4.2 interroga entrambe a ogni messaggio |
| `emitter_profile.firma_key` è la chiave storage di un'**immagine**, non un testo | `packages/core/src/pigrocrm/core/emitter/schemas.py` (in corso di implementazione) | Un'email non allega un'immagine di firma: vuole un blocco di testo — nome, ruolo, telefono, sito. Le tre parti utili esistono già come `telefono`, `sito_web`, `ragione_sociale`, ma **nome e ruolo della persona che firma non ci sono**. Da decidere: comporre la firma dai campi esistenti più `users.nome`, oppure aggiungere un `firma_email` testuale. La seconda è più semplice; la prima evita un secondo posto dove il numero di telefono può divergere |
| Nessun processo worker, e nessuna intenzione di averne uno | `docker-compose.yml` | Il §4.5 sceglie il polling su richiesta per questo. Se un giorno arriva un worker, quella scelta va rivista, non ereditata |

---

## 11. Interfaccia

- **Impostazioni → Gmail**: connetti/scollega, casella collegata, scope concessi, stato,
  `consent_expires_at`, ultimo sync, ultimo errore in italiano, interruttore
  `gmail_store_bodies`, pulsante «sincronizza adesso».
- **Banner nella shell**, persistente, con il link a Impostazioni → Gmail, in tre casi distinti e
  con tre testi distinti: `status = 'revoked'` («il consenso è stato revocato»),
  `status = 'expired'` o consenso in scadenza entro 48 ore («va rinnovato entro il …»), e scope
  insufficienti per una funzionalità attiva («il sync è spento: manca `gmail.readonly`»). Tre
  cause, tre azioni: un banner unico che dice «problema con Gmail» non aiuta nessuno.
- **Tab Email** su Cliente, Persona e Deal, dentro `EntityDetailLayout` — che era già disegnato
  per riceverla (slice 1 §10.2). Thread raggruppati, direzione visibile, «apri in Gmail» su ogni
  messaggio, «salva allegato come documento».
- **Composer**: destinatari precompilati dall'entità, corpo Markdown, allegati scelti fra i
  documenti, anteprima. Salva la bozza mentre si scrive (§6.1). Uno stato `incerto` si mostra come
  «esito da verificare», **mai** come «inviata».
- **Solleciti**: una pagina con le candidate, l'anteprima del testo, la selezione, l'invio uno a
  uno. Accanto a ogni fattura, la data dell'ultimo sollecito.
- Quando si aggiunge un indirizzo a una persona, l'interfaccia dice che le conversazioni
  compariranno al prossimo sync (§4.4), invece di lasciarlo scoprire.

---

## 12. Ciò che questo slice **non** fa

- **Nessuna ricerca full-text della casella.** Nessuna superficie, in nessun adapter, accetta una
  stringa di ricerca Gmail (§8.2).
- Nessun calendario, nessun sync dei contatti, nessuna marketing automation.
- **Nessuno script di terze parti e nessuna analitica sulla landing**, verificato dal budget del
  §9.4.
- **Nessuna registrazione pubblica.** Il prodotto resta single-tenant self-hosted (slice 1 §3).
- Nessun invio autonomo, di nulla, mai (§7.2). Nessun invio via MCP (§8.2).
- Nessun byte di allegato memorizzato, nessun rendering di HTML delle email (§5.4).
- Nessun IMAP, nessun SMTP, nessun provider diverso da Gmail. Un secondo provider è un secondo
  progetto, non un secondo `if`.
- Nessuna notifica push da Gmail (§4.6). Nessuna casella condivisa o di gruppo.
- Nessuna internazionalizzazione della landing oltre all'italiano.
- Nessuna chiusura completa di R10: solo il minimo del §8.4.

---

## 13. Criteri di successo

Eseguibili, non ammirabili. Il trasporto finto (`FakeGmail`, sul modello di `fake_drive.py`)
registra ogni richiesta ricevuta, quindi si può fare asserzione su *cosa è stato chiesto a Google*,
non solo su cosa è finito nel database.

**Sincronizzazione**

1. Una casella con 1.000 messaggi non pertinenti e 2 indirizzi noti: il sync scarica solo i thread
   di quei 2. Asserzione su **nessuna `messages.list` senza `q`** e su nessun `q` privo di un
   indirizzo noto.
2. Il sync eseguito due volte produce lo stesso numero di righe. Nessun duplicato.
3. Si aggiunge un indirizzo a una persona esistente, si esegue il sync: il thread e i suoi
   fratelli compaiono sulla persona **e** sul suo cliente. Un mittente sconosciuto incontrato
   dentro quel thread **non** entra nell'anagrafica degli indirizzi.
4. Due sync sovrapposti: il secondo risponde «già in corso» con l'ora d'inizio. Non fallisce e non
   raddoppia le richieste.

**Credenziale revocata o scaduta — il degrado si deve vedere**

5. Il trasporto finto risponde `400 invalid_grant` al refresh. Si verifica, tutto:
   (a) `status='revoked'`; (b) esiste un `activities` `gmail.credenziale_revocata`;
   (c) `GET /api/gmail/account` lo riporta; (d) un invio risponde `Conflict` con la ragione **senza
   effettuare alcuna chiamata HTTP**; (e) Playwright vede il banner nella shell dell'app;
   (f) **nessun ritentativo** del refresh; (g) `/health` è invariato.
6. Con `consent_expires_at` a 36 ore da adesso l'interfaccia avvisa **prima** che qualunque
   chiamata fallisca.
7. Concesso solo `gmail.send`: l'invio funziona, `status` resta `active`, e il sync rifiuta con un
   errore che **nomina lo scope mancante**. Le due condizioni non si confondono (§5.1).
8. Senza `PIGROCRM_GOOGLE_CLIENT_ID` l'intera suite passa e nell'app non esiste interfaccia Gmail:
   assente, non rotta. Con almeno una riga in `google_accounts` e `PIGROCRM_GOOGLE_TOKEN_KEY`
   mancante, l'API **non parte**, con un messaggio che dice quale variabile manca.

**Invio**

9. Il trasporto finto va in timeout su `messages.send`: la riga è `incerto`, l'interfaccia non dice
   «inviata», e la riconciliazione la promuove a `inviato` trovandola per `rfc822msgid`. Nella
   seconda variante — messaggio davvero assente — diventa `fallito` con la bozza intatta.
10. Due `POST /send` concorrenti sulla stessa bozza: una email, una riga, un `Conflict`.
11. Allegati per 21 MB: rifiutati **prima** di comporre, con peso e limite nel messaggio.
12. Un corpo con accenti, virgolette tipografiche ed emoji, e un oggetto con gli stessi: l'RFC822
    prodotto si ri-decodifica **identico** carattere per carattere. Nessun `Content-Transfer-Encoding:
    7bit` su testo non ASCII, in nessun ramo. È il difetto vivo del gestionale precedente (§2), verificato per non
    riprodurlo.
13. Un sollecito dentro un thread esistente porta `In-Reply-To` e `References` che puntano al
    `Message-ID` dell'invio originale.

**Solleciti**

14. Due invii concorrenti sulla stessa candidata: una email, una riga `payment_reminders`, un
    `Conflict`. La candidata esce dalla lista per `min_interval_days`.
15. Nessun invio autonomo: in tutta la suite MCP e in tutta la suite del sync, il trasporto finto
    registra **zero** chiamate a `messages.send`.

**Superficie MCP**

16. `list_tools()` non contiene alcun tool che invii, né alcun tool il cui schema accetti una
    stringa di ricerca Gmail. Verificato per nome e per schema, come già fa il test di
    architettura.
17. Un PAT senza `gmail:read` non può chiamare i tool Gmail di lettura. Creazione e revoca di un
    PAT scrivono ciascuna un `activities`.

**Landing — accessibilità, sul problema di contrasto già risolto una volta**

18. La funzione di contrasto già presente in `tokens.test.ts` viene estesa ai token
    `--landing-*`: ogni coppia testo/sfondo ≥ **4,5:1**, ogni coppia di testo grande o di
    componente ≥ **3:1**.
19. La CTA usa `--color-watermelon-strong` con testo bianco, ≥ 4,5:1. Un test verifica che
    `#ed254e` / `--color-watermelon` **non** compaia mai come riempimento pieno sotto testo bianco
    in `landing.css`. È la regressione da vietare per nome: nell'app è un problema risolto.
20. `axe-core` via Playwright, zero violazioni su tutte e tre le pagine, **con lo strato di grana
    attivo** — perché la grana sta sopra il testo.
21. Nel blocco `--landing-*` non c'è alcun esadecimale grezzo: ogni valore è un `var(--color-…)` o
    un `color-mix()` di uno. E `--landing-veil-warm` calcolato cade entro il ΔE dichiarato dal
    Coral `#FFB7B2`.

**Landing — costruzione e servizio**

22. Caricamento a freddo sotto **40 KB** trasferiti, escluso il woff2 condiviso, e **zero**
    richieste verso host esterni al proprio origin. Entrambi asserzioni Playwright su
    `page.on('request')`.
23. Con JavaScript disattivato: tutti i contenuti visibili e tutti i link funzionanti.
24. `/` serve la landing, `/app/…` serve lo SPA, un refresh su un link profondo tipo
    `/app/clienti/<uuid>` continua a funzionare, e `/privacy` e `/termini` rispondono 200 —
    verificati contro lo stack compose vero, non solo contro il dev server.
25. Ogni pagina della landing ha `title`, `meta description`, `lang="it"` e Open Graph **propri e
    coerenti col prodotto**: il `title` contiene «PigroCRM» e la `description` **non** contiene
    «AI optimization platform», la copia di un altro prodotto rimasta nello scaffold del gestionale precedente
    (§9.2). Non è pedanteria: è l'errore più facile da ripetere, ed è testo che Google legge in
    verifica.
26. `/privacy` **nomina esplicitamente** `gmail.readonly` e `gmail.send` e dice cosa il prodotto fa
    con i dati letti. È il requisito della verifica Google (§1), non una formalità: se manca,
    5B-1 resta bloccato in Testing.

---

## 14. Un piano o due? Due, e mezzo

Detto in chiaro, perché fingere il contrario produrrebbe un piano che nessuno può eseguire in
ordine:

| Piano | Contenuto | Dimensione | Bloccato da |
|---|---|---|---|
| **5A — Landing** | §9, e le prime tre righe del §10 | Piccolo. Nessun backend, nessuna migrazione, nessun servizio | Nulla. Si può fare adesso |
| **5B-1 — OAuth e sincronizzazione** | §4, §5, §8.1, il tab Email, l'indice su `customers.email` | Grande | 5A **pubblicato** (§1) e il prerequisito PAT del §8.4 |
| **5B-2 — Invio e solleciti** | §6, §7, il composer | Medio | 5B-1; slice 2 per gli allegati e `emitter_profile`; slice 3 per lo stato di pagamento |

**5A non condivide una riga di codice con 5B**; 5B-1 e 5B-2 sì — il client Gmail, `google_accounts`,
il trasporto finto — ed è precisamente perché la condividono che sono due *piani* e non due slice.
Il taglio fra 5A e 5B è di prodotto; quello fra 5B-1 e 5B-2 è di dimensione.

Fra 5A e 5B c'è **una dipendenza a senso unico**: senza 5A pubblicato, 5B vive in Testing e si
rompe ogni sette giorni.

Sequenza consigliata: **5A → prerequisito PAT → 5B-1 → 5B-2**, con la verifica Google avviata
subito dopo 5A, perché è tempo di calendario e non tempo di lavoro, e mentre scorre si costruisce
5B-1.
