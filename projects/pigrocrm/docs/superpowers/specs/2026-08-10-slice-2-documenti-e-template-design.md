# PigroCRM — Slice 2: Documenti e template

**Data:** 2026-08-10
**Stato:** da approvare
**Prerequisito:** slice 1 (Core CRM + MCP) in `main`

**Ambito:** il documentale di clienti e deal, il motore di template che produce offerte da Markdown,
il render PDF, il versioning e gli stati dell'offerta.

---

## 1. Perché questo slice esiste

Lo slice 1 ha prodotto un CRM in cui si possono descrivere clienti, persone e deal. Ma il lavoro di
un freelance non è descrivere: è **mandare un'offerta e poi ritrovarla**. Finché quella parte manca,
PigroCRM è un archivio, non uno strumento.

Il gestionale precedente faceva già questo, e lo faceva bene sotto un aspetto e male sotto un altro. Il contenuto
legale del template — definizioni, ambito, esclusioni, condizioni generali, proprietà
intellettuale, validità 15 giorni — è **materiale valido, scritto e usato in produzione**, e viene
portato così com'è. La macchina che lo riempiva no.

---

## 2. Cosa si porta dal gestionale precedente, e cosa si rifà

| Elemento | Decisione |
|---|---|
| `offer/template-offer.md` — contenuto legale | **Portato**, riscritto solo nella sintassi dei placeholder |
| `offer/pandoc-template.typst`, `offer/header.typ`, `media/` | **Portati**, con le versioni di Pandoc e Typst pinnate nell'immagine |
| Pipeline PDF Pandoc → Typst | **Portata.** Sceglierla è stata una buona decisione: Typst compone bene, è veloce, e il template è leggibile |
| Sintassi `[NOME_CLIENTE]` | **Sostituita.** Vedi §3 |
| Dati dell'intestazione hardcodati (`Humancraft di Ivan Sala`, P.IVA, PEC, sede) | **Sostituiti** da un profilo emittente configurabile. Un CRM per freelance italiani non può avere il nome di un freelance nel sorgente |
| Storage su Google Drive | **Portato come uno dei due backend.** Vedi §5 |
| Attio come sistema di record | **Rimosso, senza importer.** Vedi §8 |

---

## 3. Il motore di template

### 3.1 Perché `[NOME_CLIENTE]` va sostituito

Tre difetti, tutti dimostrati dal codice del gestionale precedente stesso:

1. **Collide con Markdown.** `[testo](link)` è un link; `[NOME_CLIENTE]` è indistinguibile da un
   riferimento incompleto, e qualunque editor Markdown lo tratta come tale.
2. **Non ha condizionali né loop.** Un'offerta con tre voci di costo e una senza IVA richiedono due
   template diversi, che divergeranno.
3. **Non ha escaping.** I valori finiscono non escapati dentro sorgente Typst. Il gestionale precedente ha un commit
   che si chiama `fix(pdf): escape @ and other typst-sensitive chars in placeholders`: la classe di
   bug è già stata incontrata e curata una volta, sintomo per sintomo.

### 3.2 Sintassi adottata

```
{{cliente.ragione_sociale}}
{{#if offerta.iva}}…{{/if}}
{{#each righe}}{{nome}} — {{totale}}{{/each}}
```

Sottoinsieme deliberato di Handlebars: variabili con percorso puntato, `#if`/`#else`, `#each` con
`this` e le proprietà dell'elemento. **Niente helper arbitrari, niente espressioni, niente chiamate
di funzione** — un template è un documento, non un programma, e un motore che esegue codice dentro
un template è una superficie di attacco che questo prodotto non ha ragione di avere.

### 3.3 Escaping per contesto di destinazione — il punto centrale

Il render è a due stadi: il template Markdown diventa Markdown compilato, che Pandoc converte in
Typst, che Typst compone in PDF. **Un valore che attraversa i due stadi va escapato per il
contesto in cui atterra, non una volta sola.**

Tre contesti, tre regole:

| Contesto | Cosa va escapato |
|---|---|
| Testo Markdown | `\` `` ` `` `*` `_` `[` `]` `<` `>` `#` a inizio riga |
| Blocco `{=typst}` grezzo | `\` `#` `$` `@` `"` `<` `>` più le sequenze di controllo |
| Attributo di un'immagine o di un link | l'URL-encoding, separatamente |

Il motore **conosce il contesto di ogni placeholder** perché parsa il template, non perché lo indovina
da una regex. Un placeholder dentro un blocco `{=typst}` viene escapato per Typst; lo stesso
placeholder in un paragrafo viene escapato per Markdown. Questa è la ragione per cui il motore non
può essere una `str.replace`.

**Test di accettazione:** una ragione sociale letterale `#import "/etc/passwd"` e una
`**Grassetto** & <script>` devono comparire nel PDF come testo, esattamente come sono state
digitate, in entrambi i contesti.

---

## 4. Modello dati

### 4.1 `documents`

Un documento appartiene a **un cliente o a un deal**, mai a entrambi e mai a nessuno dei due.

| Colonna | Tipo | Note |
|---|---|---|
| `id` | UUID v7 | |
| `customer_id` | UUID null | esattamente uno fra i due è valorizzato, vincolo di check |
| `deal_id` | UUID null | |
| `tipo` | enum | `offerta`, `contratto`, `verbale`, `documento` |
| `titolo` | String(200) | |
| `stato` | enum null | solo per `tipo = offerta`: `bozza`, `inviata`, `accettata`, `rifiutata` |
| `versione_corrente` | Integer | |
| `custom_fields` | JSONB | stesso meccanismo dello slice 1, `entity_type = 'document'` |
| `deleted_at` | timestamptz null | soft delete, come tutto il resto |

`entity_type` era già un valore aperto nello slice 1: `document` si aggiunge **senza migrazione del
validator né dello schema dei campi custom**. Era il punto del disegno.

### 4.2 `document_versions`

Ogni modifica crea una versione; **niente viene sovrascritto**.

| Colonna | Tipo | Note |
|---|---|---|
| `document_id` | UUID | |
| `numero` | Integer | progressivo per documento, unico con `document_id` |
| `sorgente_markdown` | Text null | valorizzato se generata da template |
| `template_id` | UUID null | quale template, per rigenerare |
| `variabili` | JSONB null | i valori usati, per rigenerare identico |
| `storage_key` | String | dove stanno i byte |
| `content_type`, `dimensione` | | |
| `hash_sha256` | String(64) | deduplica e verifica d'integrità |
| `creato_da` | UUID | |

Conservare `template_id` **e** `variabili` è ciò che rende una versione riproducibile: si può
rigenerare il PDF di un'offerta di sei mesi fa senza avere davanti chi l'ha scritta.

### 4.3 `templates`

| Colonna | Tipo |
|---|---|
| `nome`, `tipo`, `corpo_markdown` (Text), `variabili_dichiarate` (JSONB), `attivo` |

Le variabili sono **dichiarate**, non dedotte: il form di compilazione le mostra con etichetta, tipo
e obbligatorietà, e il render fallisce con un errore preciso se ne manca una obbligatoria — invece
di produrre un PDF con un buco.

### 4.4 `emitter_profile`

Riga singola. Ragione sociale, P.IVA, codice fiscale, indirizzo, PEC, SDI, telefono, email, logo,
firma, regime fiscale. È ciò che sostituisce i dati di Humancraft hardcodati nell'header Typst, e
**lo slice 3 ci costruisce sopra la FatturaPA**.

---

## 5. Storage pluggable

Un'interfaccia sola, due implementazioni:

```python
class DocumentStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def signed_url(self, key: str, ttl: timedelta) -> str | None: ...
```

- **`LocalFileStorage`** — default. Directory sul disco, path derivato dalla chiave, nessuna
  dipendenza esterna. È ciò che rende il prodotto self-hostable davvero.
- **`GDriveStorage`** — service account, una cartella per cliente, esattamente come il gestionale precedente le crea
  già oggi. Chi migra dal gestionale precedente ritrova le sue cartelle.

**I metadati stanno sempre in Postgres.** Ricerca, permessi, timeline e versioni funzionano identici
su entrambi i backend, e cambiare backend non perde nulla se non i byte già caricati — per i quali
serve una migrazione esplicita, non un cambio di variabile d'ambiente.

`signed_url` restituisce `None` su `LocalFileStorage`: il download passa dall'API, che è l'unico
punto in cui l'autorizzazione esiste.

---

## 6. Render PDF

Pandoc e Typst vivono **nell'immagine dell'API**, con versioni pinnate. Il render è sincrono: un
documento di poche pagine si compone in meno di un secondo, e una coda di lavori è complessità che
oggi non si ripaga.

Il servizio scrive in una directory temporanea, invoca Pandoc con il template Typst, e legge il PDF.
**Nessun input dell'utente finisce mai in una riga di comando**: i valori passano dal file sorgente,
già escapati, e i percorsi sono generati dal servizio.

Se Typst fallisce, l'errore che torna all'utente contiene **la riga del template** che l'ha causato,
non lo stderr grezzo del compilatore.

---

## 7. Superficie MCP

Stessa regola dello slice 1, non negoziabile: **i tool MCP e i router FastAPI chiamano gli stessi
servizi**, in-process, e il test di architettura lo verifica.

Tool nuovi: `list_documents`, `get_document`, `create_document_from_template`, `list_templates`,
`describe_template` (che variabili vuole), `set_offer_state`, `get_document_versions`.

`create_document_from_template` è il tool che rende vera la frase del brief originale —
*«Claude, prepara una nuova offerta usando il template Consulenza CTO»*. `describe_template` esiste
perché un agente deve poter scoprire cosa gli viene chiesto **prima** di chiedere all'utente.

Il download dei byte **non passa da MCP**: un tool che restituisce un PDF in base64 dentro un
contesto è uno spreco e un rischio. MCP restituisce un URL firmato o un identificativo.

---

## 8. Nessun importer Attio — decisione del 2026-08-20

Il piano originale prevedeva un importer una tantum da Attio, a modello dati stabilizzato. **Il
proprietario ha deciso di non usare più Attio**, quindi non c'è nulla da importare e l'importer è
rimosso dall'ambito: non è rinviato, non esiste.

Resta valida la ragione per cui Attio andava via, ed è documentata nella spec dello slice 1: il gestionale precedente
leggeva le anagrafiche da Attio tirando a indovinare gli slug dei campi fiscali — `vat_number` o
`vat` o `piva`, `sdi_code` o `codice_destinatario` o `codice_sdi` — e ogni fattura era un tiro di
dado sull'anagrafica. In PigroCRM P.IVA, codice fiscale, SDI e PEC sono colonne di prima classe, ed
è quella la sostituzione di Attio. Le anagrafiche esistenti si inseriscono a mano o, se un giorno
servisse, con un import CSV generico — che è una funzionalità diversa e non ha nulla di Attio.

## 9. Interfaccia

- Una tab **Documenti** su Cliente e su Deal, dentro `EntityDetailLayout` — che era già disegnato
  per riceverla.
- Upload con drag & drop, lista con tipo, stato, versione e data.
- **Nuovo documento da template**: si sceglie il template, si compilano le variabili dichiarate
  (con `DynamicFieldRenderer`, che copre già tutti i tipi), si vede l'anteprima Markdown, si genera
  il PDF.
- Sull'offerta: cambio stato, storico versioni, rigenerazione.
- Una pagina **Template** in Impostazioni, con editor Markdown e anteprima.

---

## 10. Ciò che questo slice **non** fa

Invio email dell'offerta (slice 5, col Gmail), firma elettronica, OCR, anteprima inline di file
Office, conversione fra formati diversi dal PDF, e qualunque forma di collaborazione in tempo reale
sul testo.

---

## 11. Criteri di successo

1. Un'offerta si crea da template, si compila, si genera in PDF e si ritrova sul deal — senza uscire
   dall'app.
2. Lo stesso risultato si ottiene da Claude via MCP, chiamando gli stessi servizi.
3. Una ragione sociale che contiene `#`, `@`, `$` o Markdown compare nel PDF come testo, non come
   codice.
4. Una versione di sei mesi prima si rigenera identica.
5. Cambiare `LocalFileStorage` con `GDriveStorage` non richiede alcuna modifica al codice dei
   servizi, e i test lo dimostrano girando su entrambi.
