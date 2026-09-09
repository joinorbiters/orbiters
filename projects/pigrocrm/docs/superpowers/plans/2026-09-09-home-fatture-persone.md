# Home, fatture dal contesto, filtro aziende, stima fiscale in Home: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sei richieste di Ivan del 2026-09-09, approvate in chat: (1) la Home mostra tutti gli stati della pipeline, con Vinto e Perso in coda; (2) dal tab Fatture del cliente si crea una fattura con il cliente già fissato; (3) dal dettaglio deal si crea una fattura con cliente e deal fissati e una riga precompilata; (4) Persone ha il filtro per azienda; (5) la scheda «Stima fiscale» entra in Home → Economica e la sezione Analisi sparisce dall'interfaccia (API e MCP restano); (6) la sincronizzazione Gmail diventa pianificabile da cron con un comando CLI, e il banner del consenso non usa più una scadenza prevista quando l'app OAuth non è più «in test».

**Architecture:** Monorepo Orbiters, progetto `projects/pigrocrm/` (tutti i percorsi sotto sono relativi a quella cartella; i comandi si lanciano dalla radice del repository). Nessuna migrazione. Il web adotta i componenti condivisi della revisione UI (`PageHeader`, `FilterRow`/`FilterChips`, `StatusPill`, `RowActions`, `NewProformaDialog`). Le API già espongono ciò che serve tranne il CLI di sync e la lettura degli stati chiusi in `pipeline_summary`.

**Tech Stack:** SQLAlchemy 2, FastAPI, Pydantic 2; React 19, TanStack Router/Query/Table v9, Tailwind v4, vitest.

**Spec:** approvazione in chat del 2026-09-09 (nessun documento separato); i vincoli della UI sono in `docs/superpowers/specs/2026-09-08-ui-revision-design.md`.

## Global Constraints

- Nessun colore nuovo: solo le cinque tinte della palette e i loro `color-mix()` verso `#ffffff` (`apps/web/src/styles/tokens.test.ts` non si allenta).
- Testi italiani, sentence case; niente maiuscole salvo le intestazioni di tabella.
- API first e MCP first: nessuna logica solo nel frontend; il MCP resta intatto (la sezione Analisi sparisce solo dalla UI).
- Ogni componente toccato resta coperto da vitest; `pnpm --filter web lint`, `npx tsc --noEmit` (in `apps/web`), `uv run ruff check projects/pigrocrm`, `uv run mypy` puliti prima di ogni commit. Test Python: `TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q <file>`.
- Worktree condiviso: ogni implementatore stage solo i propri file e committa con `git commit -- <paths>`; trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Il tool `preflight` non è installato in locale: i controlli si lanciano a mano come sopra.

---

### Task 1: Pipeline per stato, con gli stati chiusi in coda

**Files:** `packages/core/src/pigrocrm/core/deals/repository.py` (`pipeline_summary`), `packages/core/src/pigrocrm/core/dashboard/schemas.py` e `service.py` se la riga della pipeline non porta già `tipo`, test in `packages/core/tests/test_dashboard*.py` / `test_deals*.py`; web `apps/web/src/features/dashboard/CommercialTab.tsx` (+test), `apps/web/src/features/dashboard/queries.ts`, `apps/web/src/lib/api-types.ts` (rigenerare con `npm run generate:api` con l'API locale in esecuzione, oppure aggiornare a mano lo stesso shape).

**Interfaces:** `pipeline_summary()` restituisce TUTTI gli stati della pipeline configurata ordinati per `posizione`, ognuno con `stage_tipo: Literal["open","won","lost"]`; gli stati `won`/`lost` contano i deal che vi si trovano oggi (non filtrati per periodo). La card in Home si intitola «Pipeline per stato»; gli stati aperti vengono prima, poi una riga separatrice sottile e gli stati chiusi (Vinto in inchiostro, Perso in Watermelon al 10%, come già fa il badge `destructive`); le barre restano proporzionali al massimo tra tutti gli stati.

- [ ] Test (RED): repository/service restituiscono anche won/lost con `stage_tipo`; CommercialTab rende i sei stati e il separatore.
- [ ] Implementare; verde; commit `feat(dashboard): la pipeline per stato mostra anche Vinto e Perso, in coda`.

### Task 2: Nuova fattura dal cliente e dal deal

**Files:** `apps/web/src/features/invoices/NewProformaDialog.tsx` (+test), `apps/web/src/features/invoices/InvoicesTab.tsx` (+test), `apps/web/src/routes/app/clienti/$customerId.tsx` (+test), `apps/web/src/routes/app/deal/$dealId.tsx` (+test), `apps/web/src/routes/app/fatture/index.tsx` (solo se il bottone cambia firma).

**Interfaces:** `NewProformaDialog({ onClose, customerId?, dealId?, prefill?: { descrizione: string; importo: string } })`: con `customerId` il `CustomerPicker` è fissato e mostrato come testo; con `dealId` anche il `DealPicker` è fissato; `prefill` inizializza la prima riga (descrizione = nome del deal, importo = `valore_previsto`, tutto modificabile). `NewProformaButton({ customerId?, dealId?, prefill? })` esportato da `NewProformaDialog.tsx`. `InvoicesTab` accetta `actions?: ReactNode` e lo rende a destra sopra la tabella (usare la riga filtri già presente o una riga dedicata). Il dettaglio cliente passa `<NewProformaButton customerId={...} />`; il dettaglio deal aggiunge l'azione «Nuova fattura» nel `PageHeader` (prima di «Modifica») con `customerId`, `dealId` e `prefill` dal deal. Nessuna modifica backend: `POST /api/invoices` accetta già `customer_id` e `deal_id`.

- [ ] Test (RED): dialog con cliente fissato (picker assente, id inviato), con deal fissato e riga precompilata; bottone presente nel tab Fatture del cliente e nell'intestazione del deal.
- [ ] Implementare; verde; commit `feat(web): una fattura nasce anche dal cliente e dal deal, già compilata`.

### Task 3: Persone filtrate per azienda

**Files:** `apps/web/src/routes/app/persone/index.tsx` (+test), eventualmente `apps/web/src/features/people/queries.ts` per passare `customer_id`.

**Interfaces:** nella `FilterRow` un `Select` «Azienda» (opzione «Tutte le aziende» + i clienti da `useCustomers({limit:200})`, ordinati per ragione sociale) che vive nel search param `customer_id` della rotta (`validateSearch`), come la ricerca; `usePeople({search, customer_id})` lo inoltra a `GET /api/people?customer_id=` (già supportato). La colonna «Azienda» resta.

- [ ] Test (RED): il select cambia il search param e la query; il valore iniziale arriva dall'URL.
- [ ] Implementare; verde; commit `feat(web): le persone si filtrano per azienda`.

### Task 4: Stima fiscale in Home, via la sezione Analisi

**Files:** `apps/web/src/features/dashboard/EconomicTab.tsx` (+test), spostare `apps/web/src/features/analytics/FiscalPanel.tsx` (+test) e `useFiscalEstimate` in `apps/web/src/features/dashboard/` (o importarli da lì dopo lo spostamento; niente duplicati); eliminare `apps/web/src/routes/app/analisi.tsx`, `routes/app/analisi/*`, `features/analytics/{AnalyticsLayout,MarginsTable,BudgetTable,EconomicsTab,PnlRows,ToInvoiceDialog}.tsx` e i loro test, `apps/web/e2e/economics.spec.ts`; `apps/web/src/components/AppShell.tsx` (+test: via la voce «Analisi»), `apps/web/src/components/sidebarGroups.ts` se citata, `features/settings/tabs.ts` no. Verificare con `grep -rn analisi apps/web/src apps/web/e2e` che non resti nulla; `PeriodPicker` resta se usato dalla Home.

**Interfaces:** Home → Economica mostra, sotto le card e prima dei grafici, la scheda completa «Stima fiscale {anno}» (le stesse righe di oggi: ricavi, coefficiente, imponibile, aliquota sostitutiva, imposta, INPS, reddito netto, più l'avvertenza `role="note"` e il ramo 404 che rimanda a Impostazioni → Fiscale) per l'anno del periodo selezionato; il link «Apri la stima fiscale» sparisce. API `GET /api/analytics/*` e i tool MCP non cambiano.

- [ ] Test (RED): EconomicTab rende la scheda fiscale; AppShell non ha «Analisi»; nessuna rotta `/app/analisi` (il route tree si rigenera al build).
- [ ] Implementare; verde (incluso `npm run build`); commit `feat(web): la stima fiscale vive in Home, la sezione Analisi lascia l'interfaccia`.

### Task 5: Sync Gmail da cron, e un banner che non predice più

**Files:** `packages/core/src/pigrocrm/core/cli.py` (+test `packages/core/tests/test_cli*.py`), `packages/core/src/pigrocrm/core/gmail/account.py` (`health`, +test), `docs/superpowers/notes/2026-09-09-gmail-cron-runbook.md`, `README.md` (sezione deploy: il cron).

**Interfaces:** `pigrocrm gmail-sync [--email <casella>]`: esegue `GmailSyncService.sync` per l'account attivo (l'unico, o quello indicato) con un `Actor` di sistema che la ban list degli agenti non ferma (vedere come `createadmin` costruisce il contesto); stampa una riga di esito e termina 0, 1 se `revoked`/errore. Il cron sul server: `*/15 * * * * cd /opt/pigrocrm/projects/pigrocrm && docker compose --env-file ../../.env exec -T api uv run --no-sync pigrocrm gmail-sync >> /var/log/pigrocrm-gmail-sync.log 2>&1` (documentato nel runbook; lo installa il controller). `GoogleAccountService.health`: quando `settings.google_app_unverified` è falso, `consent_expires_at` viene ignorato (nessun banner «va rinnovato entro», nessun «scaduto» dedotto dalla data): la scadenza a 7 giorni esiste solo per un'app in test, e una riga scritta prima del passaggio a Internal non deve continuare a prevedere.

- [ ] Test (RED): CLI esegue il sync e riporta l'esito; `health` ignora la scadenza con app verificata e continua a segnalarla con app in test.
- [ ] Implementare; verde; commit `feat(gmail): il sync si lancia da cron con il CLI, e il banner smette di prevedere una scadenza che non c'è più`.

## Self-review

- Richieste 1→T1, 2 e 3→T2, 4→T3, 5→T4, 6 (consenso + cron)→T5. Vinto/Perso in coda: T1. «Via tutta la sezione, lascia l'MCP»: T4 tocca solo `apps/web`.
- Nomi coerenti: `NewProformaButton({customerId, dealId, prefill})`, `stage_tipo`, `pigrocrm gmail-sync`.
- Parallelismo: T1, T2, T3 sono disgiunti (dashboard/CommercialTab + core deals; invoices + due dettagli; persone). T4 tocca dashboard/EconomicTab e AppShell: parte dopo T1. T5 è solo Python + docs: parallelo a tutto.
