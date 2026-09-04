# Runbook: import dello storico fatture the previous system 2026 in PigroCRM

Slice 9A. Dataset: `docs/superpowers/data/2026-09-04-the previous system-fatture-2026.json` (14 righe,
numeri 2, 3, 5, 7–17; i numeri 1, 4, 6 non risultano emessi in the previous system e vanno dichiarati
come buchi al passo 3). Ogni riga è nel formato di `InvoiceImport`
(`packages/core/src/pigrocrm/core/invoices/schemas.py`); i campi che iniziano per `_`
(`_cliente`, `_nota`, `_avvertenze`) sono ausiliari, non fanno parte dello schema e vanno
tolti prima di inviare la riga.

**Avvertenze da chiudere prima di importare in produzione** (dettagliate anche nel primo
elemento del JSON, campo `_avvertenze`):

1. **Bollo.** Il dataset è scritto con `bollo: "0.00"` su tutte le 14 righe (quindi
   `totale = imponibile`). Nello screenshot del registro the previous system la colonna «Totale»
   coincide sempre con «Imp. Reddito», il che è compatibile sia con «niente bollo
   applicato» sia con «il bollo è già incluso in quella colonna». **Il titolare deve
   confermare contro i PDF originali** prima dell'import: se dai PDF risulta un bollo di
   2 € (dovuto sulle fatture con imponibile > 77,47 €, cioè tutte tranne la 10, la 12 e
   la 17), correggere `bollo: "2.00"` e ricalcolare `totale = imponibile + bollo` su
   quelle righe prima del passo 3 del runbook.
2. **Date di incasso.** Per le fatture con `stato_pagamento: "incassato"` (2, 3, 5, 7–13)
   il dataset porta un *placeholder*: `data_incasso = data_emissione + 30 giorni`. Non è
   la data reale — è solo un valore che soddisfa il vincolo del servizio («un incasso
   senza data non è un incasso»). **Il titolare deve sostituirla con la data reale
   dall'estratto conto bancario** prima di eseguire l'import in produzione (le fatture
   14, 15, 16, 17 restano `da_incassare` con `data_incasso: null`, corrette così).
3. **Scadenze.** `data_scadenza` è `null` su tutte le righe: verrà calcolata dal servizio
   come `data_emissione + giorni_scadenza` del profilo fiscale corrente. Se le scadenze
   reali (dai PDF) sono diverse, valorizzare `data_scadenza` riga per riga prima
   dell'import.
4. **Trasmissione esterna.** `trasmessa_esternamente_il` è `null` su tutte le righe
   (nessuna evidenza di invio/consegna nelle email per nessuna delle 14 fatture,
   compresa la 5 che risulta esplicitamente non consegnata).

## Passi

### 1. Profilo fiscale ed emittente

Compilare in Impostazioni (o via API) i dati che l'emissione/import useranno per lo
snapshot e per il calcolo della scadenza di default:

```
PUT /api/fiscal-profile
PUT /api/emitter-profile
```

Verificare in particolare `giorni_scadenza` nel profilo fiscale, perché è il valore che
il servizio userà per calcolare `data_scadenza` su tutte le 14 righe (nessuna riga del
dataset la valorizza esplicitamente).

### 2. Riavviare l'API

Il processo API in questo worktree non gira con `--reload`: dopo aver toccato
configurazione/profili, riavviarlo dal worktree prima di richiamare i tool di import.

### 3. Importare le 14 righe, in ordine di numero

Per ciascuna riga del dataset, **in ordine di `numero`** (2, 3, 5, 7, 8, 9, 10, 11, 12,
13, 14, 15, 16, 17):

1. Risolvere `_cliente` (ragione sociale esatta) in un `customer_id` reale, con
   `search_customers` sul server MCP `pigrocrm` (o `GET /api/customers?...` lato REST).
2. Costruire il payload `InvoiceImport`: prendere la riga del JSON, togliere tutte le
   chiavi che iniziano per `_` (`_cliente`, `_nota`, `_avvertenze`), impostare
   `customer_id` con l'id risolto al punto precedente.
3. Chiamare `import_issued_invoice` sul server MCP `pigrocrm` (o `POST
   /api/invoices/import` lato REST) con quel payload.
4. Verificare la risposta (numero/anno assegnati, nessun errore di validazione) prima di
   passare alla riga successiva — il servizio blocca il contatore dell'anno per riga, non
   per l'intero lotto, quindi un errore su una riga non compromette le altre già
   importate.

Al termine delle 14 righe, dichiarare i numeri mancanti 1, 4 e 6 come buchi del
registro con una sola chiamata:

```
declare_invoice_register_gaps
buchi = [
  {"numero": 1, "motivo": "<da confermare col titolare>"},
  {"numero": 4, "motivo": "<da confermare col titolare>"},
  {"numero": 6, "motivo": "<da confermare col titolare>"},
]
```

Motivo di default, se il titolare non ne indica uno più specifico: `"numero non emesso
in the previous system"`.

### 4. Verifiche post-import

- `list_invoices` (filtro `anno = 2026`, o senza filtro) deve mostrare le 14 fatture
  importate, tutte con `importata_da = "the previous system"`.
- Il contatore dell'anno deve essere avanzato al numero più alto importato più i buchi
  dichiarati: `SELECT * FROM invoice_counters WHERE anno = 2026` deve dare
  `ultimo_numero = 17`.
- `get_unbilled_backlog` (o la vista scadenziario) deve mostrare le fatture 14 e 15 come
  scadute e non incassate — coerente con `stato_pagamento = "da_incassare"` e una
  `data_scadenza` calcolata nel passato rispetto a oggi.
- `export_invoice_xml` su una qualsiasi delle 14 fatture importate deve rispondere `409`:
  un documento importato da un altro sistema non genera un XML SdI da questo.

### 5. PDF originali

Per ciascuna delle 14 fatture, recuperare il PDF originale dalla cartella Drive
`Fatture` e collegarlo come documento della fattura:

- **Finché 9C non esiste**: caricare il PDF a mano come documento (`POST
  /api/documents`, `tipo = "fattura"`) con la sua versione, poi impostare
  `pdf_sorgente = {"document_id": "<id>"}` sulla fattura importata (o rifare l'import di
  quella riga aggiungendo `pdf_sorgente` al payload, se il primo import non lo aveva
  ancora).
- **Da 9C in poi**: usare `import_drive_file` per collegare direttamente il file da
  Drive, senza il passaggio manuale di upload.

## Validazione dello schema (prima di importare qualunque cosa)

```bash
uv run --directory . python - <<'EOF'
import json
from pigrocrm.core.invoices.schemas import InvoiceImport
rows = json.load(open("docs/superpowers/data/2026-09-04-the previous system-fatture-2026.json"))
for row in rows:
    row = {k: v for k, v in row.items() if not k.startswith("_")}
    row["customer_id"] = "00000000-0000-0000-0000-000000000000"
    InvoiceImport(**row)
print(len(rows), "righe valide")
EOF
```

Atteso: `14 righe valide`. Questo controlla solo la forma (`InvoiceImport`), non le
regole del servizio (numeri liberi nel registro, cronologia, contatore) né la
risoluzione reale dei clienti — quelle si verificano solo al momento dell'import vero,
passo 3.
