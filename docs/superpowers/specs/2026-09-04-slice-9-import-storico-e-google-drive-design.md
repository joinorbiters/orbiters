# Slice 9 — Import dello storico fatture e Google Drive via MCP

**Data:** 2026-09-04
**Prerequisiti:** slice 3 (fatturazione) e slice 5 (Gmail) in albero; profilo fiscale e profilo
emittente configurati sull'installazione (oggi **mancano**: vedi §2.3).
**Ambito:** (a) registrare nel CRM le fatture già emesse con il gestionale precedente (the previous system),
senza consumare numeri né produrre XML; (b) leggere i documenti del Drive del titolare da MCP,
importarli come documenti di clienti e deal, e scrivere su quel Drive i documenti che il CRM
produce.

---

## 1. Perché adesso

Il 4 settembre 2026 il CRM ha in anagrafica sei clienti, quattordici deal e la corrispondenza
Gmail collegata, ma **zero fatture**: le quattordici emesse nel 2026 (numeri fino al 17) vivono nel registro di
the previous system e nei PDF su Drive. Senza di esse lo scadenziario (slice 8), il P&L (slice 4) e il
prossimo numero progressivo sono sbagliati: la prima fattura emessa da PigroCRM sarebbe la
**1/2026**, e il registro avrebbe due «1».

Nello stesso giorno è emerso che il CRM sa **scrivere** su Drive (slice 2, `GDriveStorage` con
service account) ma non sa **leggere** nulla di ciò che il titolare ha già lì: offerte firmate,
lettere di incarico, PDF delle fatture. Ogni volta che un importo non era nel testo di un'email,
il dato è rimasto fuori dal CRM.

Le due cose si toccano in un punto: il PDF originale di una fattura storica sta su Drive, e
l'import deve poterlo allegare.

## 2. Decisioni prese con il titolare (4 settembre 2026)

| Domanda | Decisione | Alternative scartate |
|---|---|---|
| Come caricare le 14 fatture the previous system | **Import storico dedicato**: la fattura entra come `emessa`, marcata importata, con numero e data originali, senza XML/PDF generati | Solo contatore + note (niente scadenziario); re-emissione via proforma (numeri nuovi e XML duplicati verso lo SdI) |
| Perimetro Drive via MCP | **Lettura dei documenti esistenti + scrittura dei documenti CRM** su Drive. Nessuna scrittura libera di file arbitrari | Solo lettura; scrittura libera (bypassa template, numerazione e versioning) |
| Credenziale per Drive | **OAuth dell'utente**, sullo stesso account Google già collegato per Gmail (`ivansala@humancraft.tech`) | Service account (avrebbe richiesto di condividere le cartelle con un indirizzo tecnico) |

La terza decisione contraddice una riga della spec dello slice 5 (§5.1: «Drive usa un service
account: sono due credenziali distinte e restano distinte»). Il §5 di questo documento dice come
la contraddizione viene chiusa senza riaprire il problema che quella riga proteggeva.

### 2.3 Prerequisito bloccante: profili emittente e fiscale

`describe_emitter_profile` e `describe_fiscal_profile` oggi rispondono `singleton not found`.
L'import di una fattura `emessa` congela la strategia di regime (§3.4) e il P&L legge il regime:
**senza i due profili l'import non parte**. Non è lavoro di questo slice: è la schermata
«Impostazioni» dello slice 3, da compilare prima.

---

## 3. Import dello storico fatture

### 3.1 Che cos'è una fattura importata

Una riga `invoices` con `tipo = 'fattura'`, `stato = 'emessa'`, `anno` e `numero` **dichiarati
dal chiamante** e non dal contatore, e una nuova colonna:

| Colonna | Tipo | Significato |
|---|---|---|
| `importata_da` | `String(20)` null | `'esterno'` per questo slice (era `'the previous system'`, rinominato dalla migrazione 0029: il valore raggiunge API e schermo, quindi non nomina nessun prodotto). `NULL` = emessa da PigroCRM. È il campo che dice «di questa fattura il CRM non ha prodotto né XML né PDF» |

Tutto il resto è il modello dello slice 3: `imponibile`, `imposta`, `bollo`, `totale`,
`data_emissione`, `data_scadenza`, `stato_pagamento`, `data_incasso`, `causale`,
`trasmessa_esternamente_il`, righe in `invoice_lines`, `snapshot` del regime.

**Cosa non ha, per costruzione:** `xml_hash_sha256` (resta `NULL`), `xml_document_id` (resta
`NULL`). `export_xml` su una fattura importata solleva `Conflict` con il testo «fattura importata
da the previous system: l'XML è quello già trasmesso allo SdI dal gestionale precedente». Il PDF è
**facoltativo** e, se c'è, è l'originale caricato (§3.5), mai un rendering nuovo: un PDF
ricreato oggi con un layout diverso non sarebbe la fattura che il cliente ha ricevuto.

### 3.2 Regole di registro

Le stesse dello slice 3, applicate ai numeri dichiarati:

1. **Unicità** di `(anno, numero)` fra tutte le fatture `emessa` e `annullata` — è il vincolo
   già presente (`uq_invoices_anno_numero`).
2. **Monotonia cronologica**: `data_emissione` non può precedere quella della fattura con
   numero immediatamente inferiore già presente, né seguire quella con numero immediatamente
   superiore. Il controllo dello slice 3 guarda solo «l'ultima»; l'import inserisce in mezzo,
   quindi guarda i due vicini.
3. **Il contatore avanza, mai indietro.** Dopo ogni import, `InvoiceCounter(anno).ultimo_numero
   = max(ultimo_numero, numero)`. Con le fatture 2–17 importate il contatore 2026 vale 17 e la
   prossima emissione è la 18.
4. **I buchi si dichiarano.** Nel registro the previous system del 2026 mancano 1, 4 e 6. L'import **non**
   li inventa e non li blocca: il chiamante passa `buchi_dichiarati: [1, 4, 6]` con un motivo
   testuale per ciascuno (es. «annullata in the previous system prima della trasmissione»). Il servizio scrive
   una riga `invoice_register_gaps(anno, numero, motivo, dichiarato_da, dichiarato_il)`. Un
   numero mancante **non dichiarato** fra 1 e `ultimo_numero` è un errore
   dell'import, non un avviso: il registro senza buchi è la proprietà che lo slice 3 esiste per
   difendere, e un buco muto è indistinguibile da una fattura persa. Il limite inferiore è **1**,
   non il minimo importato: il registro di un anno comincia sempre dall'1, quindi un 1 mancante è
   un buco esattamente come un 8 mancante — ed è proprio il caso del 2026 di the previous system, la cui prima
   fattura è la 2.
5. **Solo anni chiusi o l'anno corrente fino a oggi**: `data_emissione` non nel futuro.
6. **Nessun import dopo la prima emissione nativa dello stesso anno**, salvo numeri inferiori
   al primo emesso da PigroCRM. Tradotto: si importa lo storico *prima* di cominciare, o si
   riempie il passato, mai si infila un numero sopra quelli già emessi qui.

### 3.3 Dati in ingresso

`InvoiceImport` (Pydantic, tutti i testi `SafeStr`):

```
anno, numero, data_emissione, data_scadenza?, customer_id, deal_id?,
causale?,                                      # es. "900142/0426/Consulenza AI CTO progetto Aurora"
righe: [{descrizione, quantita, prezzo_unitario, prezzo_totale, aliquota_iva, natura?}],
imponibile, imposta, bollo, totale,           # dichiarati, non ricalcolati (vedi sotto)
stato_pagamento, data_incasso?,
trasmessa_esternamente_il?,                    # data di trasmissione SdI da the previous system
pdf_sorgente?: {drive_file_id} | {upload_key}, # §3.5
note_interne?, importata_da: "esterno"
```

`riferimento` non c'è, di proposito: sulla tabella `invoices` è il riferimento di una **proforma**
(vincolo `ck_invoices_riferimento_only_on_proforma`), e la descrizione che the previous system stampava
(«900142/0426/…») è una causale, quindi va in `causale` e nella riga.

**I totali sono dichiarati e verificati, non ricalcolati.** Il documento fiscale è quello
emesso da the previous system: il CRM deve registrare *quel* totale. Ma verifica che `imponibile + imposta =
totale` e che `imponibile = Σ prezzo_totale di riga` al centesimo; una discordanza è un
`ValidationFailed` che nomina i due valori. Il **bollo non entra nel totale**: si dichiara a
parte (verificato non negativo, mai sommato), perché `DatiBollo/BolloVirtuale` afferma che è
l'emittente ad averlo assolto in modo virtuale — è la stessa identità che `sum_totals` dello
slice 3 (§6.1 regola 4 e §7.2) scrive per una fattura emessa qui, e il registro the previous system concorda:
la colonna «Totale» coincide sempre con «Imp. Reddito». È lo stesso principio dei totali dello slice 3 §6.1,
letto al contrario: lì il CRM calcola e il documento segue, qui il documento comanda e il CRM
controlla che i conti tornino.

### 3.4 Snapshot del regime

L'import congela `snapshot` dal profilo fiscale corrente, come `issue`. Il regime forfettario
non è cambiato nel 2026 e le 14 fatture sono tutte a `imposta = 0`, quindi il valore è corretto;
se un giorno l'import dovesse riguardare un anno con regime diverso, `InvoiceImport` accetterà
un `snapshot` esplicito. Non in questo slice: YAGNI.

### 3.5 Il PDF originale

Due sorgenti, una alla volta:

- `{"drive_file_id": ...}` — il file viene letto dal Drive del titolare con la credenziale del
  §5, salvato nello storage documenti come `documents.tipo = 'fattura'` con una versione, e
  collegato in `pdf_document_id`. Il byte non viene modificato: `hash_sha256` della versione è
  quello del file su Drive.
- `{"upload_key": ...}` — un file già caricato via REST (`POST /api/documents/upload`, slice 2).

Senza `pdf_sorgente` la fattura importata non ha PDF: `render` risponde `Conflict` «fattura
importata senza PDF originale», non genera.

### 3.6 Superficie

| Dove | Cosa |
|---|---|
| `InvoiceService.import_issued(data, actor)` | Una transazione: lock del contatore dell'anno (stesso `SELECT … FOR UPDATE` di `issue`), controlli §3.2, insert, avanzamento contatore, `activities` `invoice.importata` con `anno/numero/importata_da` |
| `InvoiceService.declare_gaps(anno, [{numero, motivo}], actor)` | Scrive `invoice_register_gaps`; `activities` `invoice.buco_dichiarato` |
| REST `POST /api/invoices/import` e `POST /api/invoices/{anno}/gaps` | Ruolo `admin`; PAT accettato come ovunque |
| MCP `import_issued_invoice`, `declare_invoice_register_gaps` | In `tools/privileged.py`, quindi solo con `mcp_full_access`: **scrivono nel registro fiscale**, e la lista dei divieti agli agenti (`AGENT_FORBIDDEN_ACTIONS`) cresce di due voci, con i test di `test_mcp_invoice_ban.py` aggiornati a diciannove |
| Frontend | Fuori ambito: il titolare importa via MCP o REST. La lista fatture mostra il badge «importata da the previous system» e nasconde i pulsanti XML/rigenera su quelle righe |

### 3.7 L'import concreto di settembre 2026

Quattordici fatture (numeri 2, 3, 5, 7–17), tutte con dati già ricostruiti dalle email e dal
registro the previous system (screenshot del 4/09). Tutti e sei i clienti esistono già nel CRM; i PDF stanno nella cartella
`Fatture` del Drive humancraft. La fattura 5/00 (Bianchi) è «emessa e non consegnata» in the previous system:
si importa con `trasmessa_esternamente_il = NULL` e nota, e resta un residuo da chiudere con il
codice fiscale del cliente. Sequenza: profili (§2.3) → collegamento Drive (§5) → import 2, 3, 5,
7…17 in ordine di numero → buchi 1, 4, 6 dichiarati → verifica che `list_invoices` dia 14 righe
e `get_unbilled_backlog`/scadenziario tornino con 14 e 15 scadute.

---

## 4. Google Drive: cosa si legge e cosa si scrive

### 4.1 Le cartelle del titolare

Il Drive humancraft ha, alla radice: `Progetti`, `Offerte`, `Meet Recordings`, `Fatture`,
`ALTRO`, più file sciolti (lettere di incarico Acme, prompt). Il CRM **non** assume questa
struttura: è il titolare che, dall'app, indica la **cartella radice** che il CRM può vedere (una
o più: `Offerte`, `Fatture`, `Progetti`). Tutto fuori da quelle cartelle non esiste per il CRM,
esattamente come per Gmail esiste solo ciò che il `q` seleziona. `Meet Recordings` e `ALTRO`
restano fuori finché non vengono indicate.

### 4.2 Lettura: tre tool MCP

| Tool | Cosa fa | Cosa non fa |
|---|---|---|
| `list_drive_files(cartella_id?, cursor?)` | Elenca file e sottocartelle **dentro le radici configurate**: id, nome, mime, dimensione, modificato il, cartella. Paginato | Nessuna ricerca full-text su Drive: la query verso Google è `'<id> in parents'`, mai un `name contains` con testo dell'agente. Stessa regola del §4 dello slice 5: il filtro è strutturale, non una stringa |
| `read_drive_file(file_id)` | Restituisce il **testo** di un PDF, Google Doc, `.docx` o `.md` (fino a `PIGROCRM_DRIVE_TEXT_MAX_BYTES`, default 256 KB) con `provenienza: "file del titolare"`. Per un Google Doc chiede l'export `text/plain`; per un PDF estrae il testo con lo stesso estrattore dei test di slice 2 | Non restituisce byte, non immagini, non fogli. Un file fuori dalle radici configurate è `NotFound`, anche se l'id è valido |
| `import_drive_file(file_id, customer_id | deal_id, tipo, titolo)` | Copia il file nello storage documenti come `documents` + versione, `tipo` ∈ {`offerta`, `contratto`, `fattura`, `documento`}, e restituisce l'id documento. L'`activities` registra `document.importato_da_drive` con `drive_file_id` | Non sposta né cancella nulla su Drive |

Il testo di un file, come il corpo di un'email, è **testo scritto da qualcun altro**:
`read_drive_file` lo etichetta come non attendibile nello stesso modo di `get_gmail_message`.

Divergenza registrata in implementazione (9C): l'attività scritta da `import_drive_file` è
`document.importato`, non `document.importato_da_drive` come dice la tabella qui sopra — un
solo `kind` per «byte importati dentro il CRM», con `origine.drive_file_id` a dire da dove
vengono, così che una seconda provenienza (una casella, un upload) non richieda un terzo
`kind` per la stessa cosa.

### 4.3 Scrittura: il CRM, non l'agente

Non esiste un `write_drive_file`. Ciò che il CRM produce — offerte da template, proforma, PDF e
XML di fattura, rapporti ore, solleciti — finisce su Drive perché lo **storage documenti** è
Drive: `PIGROCRM_STORAGE_BACKEND=gdrive` con la credenziale del §5, una cartella per cliente
sotto la radice `PigroCRM` scelta dal titolare (la convenzione già scritta in `gdrive.py`). Un
agente crea un'offerta con `create_document_from_template` e la trova su Drive; non scrive un
file a mano. Il versioning, la numerazione e i template restano quelli del CRM.

La migrazione dei byte già su storage locale non è automatica (slice 2 §5: «serve una
migrazione esplicita»). Oggi lo storage locale contiene zero documenti: si parte direttamente
con `gdrive`.

---

## 5. La credenziale: OAuth dell'utente, con un consenso separato

### 5.1 Perché la spec dello slice 5 diceva di no, e cosa cambia

La riga «due credenziali distinte» del §5.1 dello slice 5 difendeva due cose: non chiedere in
una schermata di consenso più del necessario, e non far diventare il refresh token Gmail una
chiave che apre anche altro. Entrambe restano vere con una scelta precisa:

**Drive è un secondo grant OAuth, sullo stesso account Google, con i propri scope e la propria
riga.** Non si aggiunge `drive.*` al consenso Gmail. Il titolare preme «Collega Drive» in
Impostazioni, vede una schermata con *solo* gli scope Drive, e il refresh token che ne esce è
sigillato in una riga separata. Revocare Drive non tocca Gmail e viceversa.

| Scope | Serve per | Perché non basta di meno |
|---|---|---|
| `openid`, `email` | Rifiutare un grant che punta a un account diverso da quello Gmail (`sub` confrontato) | Un Drive di un altro account sarebbe un errore silenzioso |
| `https://www.googleapis.com/auth/drive.readonly` | §4.2: elencare e leggere dentro le radici configurate | `drive.file` vede solo i file creati dall'app: nessuno dei PDF esistenti |
| `https://www.googleapis.com/auth/drive.file` | §4.3: creare e aggiornare i file che il CRM produce | `drive.readonly` non scrive; `drive` (pieno) darebbe cancellazione e scrittura su tutto, che nessuna funzionalità richiede |

Scope **non richiesti**: `drive` pieno, `drive.metadata`, `drive.appdata`.

### 5.2 Modello dati

Non si riusa `google_accounts` con colonne in più: quella riga è la casella di posta e il suo
`status` risponde alla domanda «la sincronizzazione può girare?». Una tabella gemella:

`google_drive_accounts` — `user_id` (unica), `google_sub`, `email_address`,
`refresh_token_ciphertext`, `refresh_token_nonce` (stessa `seal` e stessa chiave
`PIGROCRM_GOOGLE_TOKEN_KEY`), `scopes_granted`, `status` (`active`, `revoked`, `expired`),
`consent_expires_at`, `root_folder_ids` (JSONB, le radici del §4.1), `storage_folder_id` (la
radice di scrittura del §4.3), `last_error`, `last_error_at`, `connected_at`,
`disconnected_at`.

Il vincolo `google_sub` uguale a quello di `google_accounts` dello stesso utente è controllato
al callback e non nel database: l'account Gmail può essere collegato dopo il Drive, e il
controllo vale in entrambe le direzioni al momento in cui il secondo arriva.

### 5.3 La seconda credenziale e i PAT (slice 5 §8.4, di nuovo)

Il §8.4 dello slice 5 ha stabilito che una capacità Google su un PAT richiede uno scope PAT
esplicito e una scadenza. Vale identico qui: i tre tool del §4.2 richiedono lo scope PAT
`drive:read`, `import_drive_file` anche `documents:write`; un PAT con scope `drive:*` ha
`expires_at` obbligatorio. Un PAT emesso per «leggi i miei deal» non legge il Drive.

### 5.4 Trasporto

`gdrive.py` oggi firma un JWT di service account per ottenere il token. Il §4 ha bisogno dello
stesso client HTTP con un token utente: il client si scompone in **`DriveTransport`** (URL,
multipart, errori, retry: il codice esistente) e **due fornitori di token** — il service account
di oggi e `GoogleTokenClient.refresh` dello slice 5 con il refresh token di
`google_drive_accounts`. `GDriveStorage` accetta un fornitore di token invece del JSON del
service account; il service account resta supportato per chi lo aveva configurato. Il fake
`fakes/fake_drive.py` non cambia: è il trasporto che finge, e il trasporto è lo stesso.

### 5.5 Diagnosi, non tentativi

`describe_drive_account` (MCP, sempre registrato quando Google è configurato) risponde come
`describe_gmail_account`: `banner` fra `revoked`, `expiring`, `expired`, `missing`, le radici
configurate, l'ultimo errore. Ogni tool del §4.2 rifiuta con un errore che nomina il banner
invece di riprovare.

### 5.6 Durata dell'autenticazione: sei mesi, per entrambe le credenziali

Richiesta esplicita del titolare (4 settembre 2026): «l'auth scade dopo 6 mesi, mi sono
scocciato di rifare il login in continuazione». Oggi il login si rifà per due ragioni diverse,
e vanno chiuse entrambe:

| Cosa scade oggi | Perché | Cosa cambia |
|---|---|---|
| **Sessione dell'app**: `refresh_token_days = 30` | Default dello slice 1 | Default a **180 giorni**, e la rotazione del refresh token **rinnova la scadenza a ogni uso** (sliding): chi usa il CRM non rivede il login; chi lo lascia fermo sei mesi sì. `PIGROCRM_REFRESH_TOKEN_DAYS=180` sull'installazione. L'access token resta a 15 minuti: è la finestra di revoca, non la durata della sessione |
| **Consenso Google**: `consent_expires_at` a 7 giorni | `PIGROCRM_GOOGLE_APP_UNVERIFIED=true`: il progetto OAuth su Google Cloud è in modalità *Testing*, e Google fa scadere i refresh token consumer dopo sette giorni. Non è una scelta del CRM e nessun codice può allungarla | Il progetto OAuth passa a **pubblicato**. Poiché `ivansala@humancraft.tech` è un account Google Workspace, il tipo utente **Internal** (solo utenti del dominio humancraft.tech) non richiede la verifica di Google per gli scope sensibili di Gmail e Drive. Con l'app pubblicata il refresh token non ha scadenza fissa: Google lo revoca solo dopo **sei mesi di inutilizzo**, e il sync Gmail lo usa ogni giorno. Poi `PIGROCRM_GOOGLE_APP_UNVERIFIED=false`, così `consent_expires_at` resta `NULL` e il banner di scadenza non compare più |

Il grant Drive del §5.1 nasce già sotto queste regole: stesso progetto OAuth pubblicato, nessuna
scadenza imposta dal CRM, `consent_expires_at` valorizzato solo se l'installazione dichiara
ancora l'app come non verificata. Il CRM **non aggiunge mai** una scadenza propria a una
credenziale Google: la durata è quella che Google concede, e la sola cosa che il CRM fa è
tenerla viva usandola.

La pubblicazione del progetto OAuth è un'azione del titolare nella Google Cloud Console, non un
task di codice: va fatta prima di 9B, perché collegare Drive con l'app ancora in Testing
produrrebbe un secondo consenso da rifare ogni settimana.

---

## 6. Ciò che questo slice **non** fa

- Nessuna ricerca per nome o testo su Drive da parte di un agente (§4.2). Nessun `write_drive_file`.
- Nessuna lettura fuori dalle radici configurate. Nessun accesso a Drive condivisi di terzi.
- Nessuna sincronizzazione periodica di Drive: si legge a richiesta, non si specchia.
- Nessuna migrazione dei byte da storage locale a Drive (oggi non ce ne sono).
- Nessun import di fatture con `imposta ≠ 0` o regime diverso da quello corrente senza snapshot esplicito (§3.4).
- Nessuna generazione di XML o PDF per le fatture importate (§3.1).
- Nessuna schermata frontend per l'import (§3.6); il badge «importata» sì.
- Nessun OCR: un PDF senza layer di testo restituisce testo vuoto e lo dice.

---

## 7. Come si verifica

1. **Registro.** Importare 2, 3, 5, 7–17 del 2026 in ordine casuale produce lo stesso registro
   che in ordine crescente; un import con `(2026, 9)` duplicato è `Conflict`; una `data_emissione`
   che rompe la monotonia rispetto ai vicini è `ValidationFailed`; il contatore vale 17; una
   `issue` successiva dà la 18; un numero mancante non dichiarato blocca l'ultimo import con un
   messaggio che elenca i buchi.
2. **Totali.** `imponibile + imposta + bollo ≠ totale` è rifiutato al centesimo, con i due valori
   nel messaggio.
3. **XML.** `export_xml` su una fattura importata è `Conflict`; `list_invoices` la mostra con
   `importata_da = "esterno"`.
4. **Drive, relevance.** Il fake trasporto registra ogni richiesta: ogni `files.list` porta
   `'<id> in parents'` con un id fra le radici configurate e **nessun** `name contains`, `fullText
   contains` o `q` privo di `in parents`. Un `read_drive_file` su un id fuori radice è `NotFound`
   senza chiamare Google.
5. **Credenziale.** Il grant Drive con `sub` diverso dall'account Gmail è rifiutato; la revoca di
   Drive lascia `google_accounts` intatta; un PAT senza `drive:read` non vede i tre tool.
6. **Storage.** Con `storage_backend=gdrive` e token utente, `create_document_from_template`
   scrive il PDF sotto `<radice>/<cliente>/…` e `download` lo rilegge identico; il service
   account continua a passare gli stessi test.
7. **Sessione.** Con `refresh_token_days=180` un refresh al giorno 179 produce un token valido
   altri 180 giorni; un consenso Google registrato con `google_app_unverified=false` ha
   `consent_expires_at = NULL` e `describe_gmail_account`/`describe_drive_account` non mostrano
   alcun banner di scadenza.
8. **MCP.** I due tool di import stanno in `privileged.py` e nella lista dei divieti; i tre di
   lettura hanno solo parametri `id`/`cursor`/enum (nessuna stringa libera), verificato dal test
   di schema dello slice 5 esteso a questa superficie.

---

## 8. Sequenza di consegna

1. **9A — Import storico**: colonna `importata_da`, tabella `invoice_register_gaps`,
   `import_issued`, `declare_gaps`, REST, tool privilegiati, badge in lista. Sbloccato da §2.3.
2. **9B — Credenziale Drive e durata dell'autenticazione**: `google_drive_accounts`, flusso
   OAuth separato, `DriveTransport` e fornitori di token, `describe_drive_account`, scope PAT;
   `refresh_token_days` a 180 con rotazione sliding (§5.6). Preceduto dalla pubblicazione del
   progetto OAuth da parte del titolare.
3. **9C — Lettura e import da Drive**: i tre tool, estrazione testo, `import_drive_file`, e il
   collegamento con `pdf_sorgente` di 9A.
4. **9D — Storage su Drive con token utente**: `GDriveStorage` sul nuovo trasporto,
   `storage_backend=gdrive` sull'installazione.

9A e 9B sono indipendenti e possono procedere in parallelo; 9C dipende da entrambi; 9D da 9B.
