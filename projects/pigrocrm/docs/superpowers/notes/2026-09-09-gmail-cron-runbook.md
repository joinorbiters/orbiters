# Runbook: il sync Gmail da cron, e il banner che non prevede più una scadenza

Due cose decise insieme, perché insieme rispondono alla stessa domanda dell'operatore
(«la casella si sincronizza da sola, e se smette me ne accorgo?»):

1. `pigrocrm gmail-sync`, un comando che esegue **un ciclo** di sincronizzazione e
   termina. Non è un demone: questo prodotto non ha un processo worker e non ha una
   coda (vedi la docstring di `packages/core/src/pigrocrm/core/gmail/sync.py`), quindi i
   quindici minuti li tiene cron.
2. Il banner di scadenza del consenso, che ora esiste **solo** finché il progetto OAuth
   è in Testing.

## 1. Installare il cron (operatore, sul server)

Una riga in `crontab -e` dell'utente che possiede il deploy (quello che può parlare con
il socket di Docker):

```
*/15 * * * * cd /opt/pigrocrm/projects/pigrocrm && docker compose --env-file ../../.env exec -T api uv run --no-sync pigrocrm gmail-sync >> /var/log/pigrocrm-gmail-sync.log 2>&1
```

Quattro dettagli della riga non sono decorativi:

- **`cd /opt/pigrocrm/projects/pigrocrm`**: `docker compose` legge `docker-compose.yml`
  dalla directory corrente, e cron parte dalla home dell'utente, non da lì.
- **`--env-file ../../.env`**: il `.env` del server sta nella radice del repository, non
  accanto al compose file, e compose cerca `.env` nella *propria* directory. Senza
  questo, ogni interpolazione risulta vuota (è lo stesso motivo del commit `84a4c2d`,
  ed è la stessa opzione che serve a ogni altro comando compose su questo server).
- **`exec -T api`**: `exec` e non `run`, perché il container `api` è già in piedi e un
  `run` ne avvierebbe un secondo con la stessa configurazione ogni quarto d'ora. `-T`
  disattiva la pseudo-TTY, che cron non ha.
- **`uv run --no-sync`**: senza `--no-sync`, `uv` risincronizza l'ambiente del container
  di produzione contro l'intero `pyproject.toml`, gruppo `dev` incluso, e si scarica
  mypy e ruff dentro un container in esecuzione. È già successo una volta, dal vero
  (vedi `Dockerfile.api` e il §5 del README).

Verifica subito, senza aspettare il quarto d'ora, eseguendo la stessa riga a mano: deve
stampare una riga sola e uscire con stato 0.

```
cd /opt/pigrocrm/projects/pigrocrm && docker compose --env-file ../../.env exec -T api uv run --no-sync pigrocrm gmail-sync; echo "uscita: $?"
```

Se l'installazione ha più di una casella Google collegata, il comando **si rifiuta di
indovinare** e le elenca: in quel caso serve una riga di cron per casella, ciascuna con
`--email casella@dominio.it`. Scegliere per conto dell'operatore vorrebbe dire lasciare
l'altra casella non sincronizzata, con un log identico nei due casi.

## 2. Leggere il log

Ogni esecuzione scrive **una riga sola**, che comincia con l'ora UTC in ISO 8601 (cron
non ne aggiunge nessuna, e un log di frasi senza orario non risponde alla prima domanda
che gli si fa: da quando non funziona più).

Ciclo eseguito, su `stdout`, uscita `0`:

```
2026-09-09T03:15:02+00:00 gmail-sync io@example.it: 4 messaggi nuovi, 11 già presenti, 3 conversazioni lette, 6 collegamenti, 0 invii riconciliati (2 query)
```

- **messaggi nuovi / già presenti**: la finestra si sovrappone di proposito a quella del
  ciclo precedente (`PIGROCRM_GMAIL_WATERMARK_OVERLAP_HOURS`), quindi «già presenti» è
  alto per costruzione e non è uno spreco: è il vincolo di unicità che assorbe un
  messaggio arrivato a cavallo di due esecuzioni.
- **query**: `0` significa che nessun indirizzo del CRM era da cercare, e quindi che a
  Google non è stata fatta **nessuna** richiesta, nemmeno il refresh del token. Su
  un'installazione senza clienti né persone con un indirizzo è la riga giusta, non un
  guasto.
- **invii riconciliati**: quante mail partite con esito ignoto sono state risolte in
  questo ciclo, in un verso o nell'altro.

Ciclo già in corso (un altro cron, o qualcuno che ha premuto Sincronizza), sempre su
`stdout`, uscita **`0`**:

```
2026-09-09T03:15:02+00:00 gmail-sync io@example.it: già in corso da 2026-09-09T03:14:58+00:00
```

Non è un errore: è il lucchetto che fa il suo mestiere, il secondo chiamante non ha
speso niente e mettere un errore nel log per il sistema che funziona come progettato è
il modo migliore per insegnare all'operatore a ignorare il log.

Guasto, su `stderr`, uscita **`1`**:

```
2026-09-09T03:15:02+00:00 gmail-sync: il consenso Google per io@example.it è stato revocato: ricollega la casella da Impostazioni → Gmail
```

Le frasi che si possono leggere qui, e cosa fare:

| Frase | Cosa è successo | Cosa fare |
| --- | --- | --- |
| `nessuna casella Google collegata` | Il cron è installato su un'installazione dove nessuno ha mai collegato Gmail (o l'unica casella è stata scollegata: una casella scollegata non viene né scelta né elencata) | Collegarla da Impostazioni → Gmail, o togliere la riga di cron |
| `la casella … appartiene a un utente disattivato` | Il titolare ha disattivato l'utente proprietario della casella | Riattivare l'utente, oppure scollegare la casella e togliere il cron. Il consenso di chi è stato disattivato non si spende |
| `… ha il ruolo readonly e non può sincronizzare …` | Il proprietario della casella non ha un ruolo che può scrivere | Cambiare il ruolo dell'utente: il cron non agisce con più diritti del titolare della casella |
| `più di una casella collegata, indica --email: …` | Più caselle, nessuna indicata | Una riga di cron per casella, con `--email` |
| `… non è una casella collegata: …` | `--email` non corrisponde a nessuna riga | Correggere l'indirizzo (il messaggio elenca quelli collegati) |
| `il consenso Google … è stato revocato` | Google ha risposto `invalid_grant`: terminale, non si risolve riprovando | Il titolare rifà il collegamento da Impostazioni → Gmail |
| `il consenso Google … è scaduto` | I sette giorni della modalità Testing sono finiti | Come sopra, e vedi il §3 qui sotto |
| `manca l'autorizzazione https://www.googleapis.com/auth/gmail.readonly` | Il consenso c'è ma è parziale | Ri-autorizzare dalla pagina Impostazioni |
| `Gmail non è configurato su questa installazione` | Mancano le variabili `PIGROCRM_GOOGLE_*` | `.env` + riavvio dell'API, oppure togliere il cron |
| `elenco dei messaggi fallita (429/RESOURCE_EXHAUSTED)` | Quota Gmail esaurita per ora | Niente: il ciclo dopo riprende da dove era arrivato |

Un errore *non previsto* stampa invece il suo traceback ed esce comunque con stato
diverso da 0: è voluto, perché un guasto che nessuno ha previsto merita il suo stack.

Il log non contiene mai un oggetto, un indirizzo di un corrispondente o un corpo di
messaggio: quello che il comando stampa sono i contatori di `SyncReport`, dove non c'è
spazio per nient'altro. È questo che rende sicuro appenderlo a un file sull'host.

**Rotazione**: `/var/log/pigrocrm-gmail-sync.log` cresce di circa 100 caratteri ogni
quarto d'ora (~3,5 MB l'anno). Se sul server c'è `logrotate`, una regola settimanale con
`rotate 8` basta e avanza; senza, va bene anche non farne nulla per un anno.

## 3. Il banner smette di prevedere

`GoogleAccountService.health` legge `consent_expires_at` **solo** quando
`PIGROCRM_GOOGLE_APP_UNVERIFIED=true`, cioè solo quando il progetto OAuth è ancora in
Testing — l'unica modalità in cui Google fa scadere davvero il refresh token, dopo sette
giorni. Pubblicato il progetto (vedi
[`2026-09-04-google-oauth-publish-runbook.md`](2026-09-04-google-oauth-publish-runbook.md)),
le righe scritte prima portano ancora la loro data, ma quella data non descrive più
niente: lasciata a prevedere, chiederebbe di rinnovare un consenso che non sta per
scadere e poi lo dichiarerebbe morto in un giorno in cui non è successo nulla.

Quindi, con `PIGROCRM_GOOGLE_APP_UNVERIFIED=false`:

- niente più banner «va rinnovato entro il …» né «è scaduto» dedotti dalla data;
- e niente più data nemmeno nella pagina Impostazioni → Gmail: il `consent_expires_at`
  che la pagina rende accanto all'indirizzo («Consenso da rinnovare entro il …») esce
  dallo stesso `health`, quindi passa per lo stesso filtro. Toglierla dal solo banner
  avrebbe spostato la frase, non rimossa;
- resta invece tutto ciò che è un **fatto**: `status = revoked` (che il CRM impara solo
  da un `invalid_grant` di Google), `status = expired`, un consenso parziale, una casella
  scollegata dal titolare. Il banner riporta quelli esattamente come prima.

La colonna `consent_expires_at` non viene ripulita: è il registro di ciò che era vero
sotto il consenso che l'ha scritta, e rimettere l'app in Testing la rende di nuovo
significativa senza dover ricostruire niente.

**Attenzione, e non è una contraddizione**: un consenso *dato* mentre il progetto era in
Testing scade davvero, anche dopo la pubblicazione — Google non guarisce un token già
emesso. Il passo 6 del runbook di pubblicazione (ricollegare la casella una volta) serve
ancora. La differenza è come lo si scopre: non più da una previsione del CRM, ma da
Google che risponde `invalid_grant`, che è un fatto, e che questo cron scrive nel log
la prima volta che capita.
