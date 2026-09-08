# Slice 9D — Storage documenti su Drive con token utente: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** I documenti che il CRM produce (offerte, proforma, PDF e XML di fattura, rapporti ore, solleciti) finiscono sul Drive del titolare, in una cartella per cliente sotto la radice di scrittura scelta in Impostazioni → Drive, usando la credenziale OAuth utente di 9B. Nessun tool che scrive file: scrive il CRM.

**Architecture:** 9B ha già reso `GDriveStorage` indipendente dal fornitore di token. Qui: la fabbrica dello storage sceglie il token utente quando non c'è un service account; la radice di scrittura è `google_drive_accounts.storage_folder_id`; il flusso `PUT/GET/DELETE/signed_url` è quello esistente, verificato con il token utente e con lo scope `drive.file`; `verify_root_accessible` diventa parte di `set_roots` (fallisce subito se la cartella non è scrivibile) invece che dell'avvio dell'API, perché la radice può non esistere ancora quando il processo parte.

**Tech Stack:** come 9B.

**Spec:** `docs/superpowers/specs/2026-09-04-slice-9-import-storico-e-google-drive-design.md` §4.3, §5.4, §6.

## Global Constraints

- `PIGROCRM_STORAGE_BACKEND=gdrive` senza `PIGROCRM_GDRIVE_SERVICE_ACCOUNT_JSON` significa «token utente dell'account Drive collegato»; con il service account il comportamento di oggi non cambia (test `test_gdrive*.py` invariati).
- Con `gdrive` e nessun account Drive collegato o nessuna `storage_folder_id`, ogni `put` solleva un errore guidato («collega Drive e scegli la cartella di scrittura in Impostazioni → Drive»), mai uno stack Google; `get` di documenti già su storage locale continua a funzionare solo se il backend è ancora `local` (la migrazione dei byte non è in ambito: spec §6).
- I file scritti portano la `storage key` in `appProperties` come oggi (identità per proprietà, non per percorso).
- Nessun tool MCP nuovo. Nessuna cancellazione su Drive oltre a quella che `DocumentStorage.delete` già fa per le versioni eliminate.
- Formattazione e lint prima di ogni commit; messaggi `feat(storage): ...`.

---

### Task 1: La fabbrica sceglie il token utente

**Files:** `packages/core/src/pigrocrm/core/storage/factory.py`, `packages/core/src/pigrocrm/core/config.py` (docstring di `storage_backend`), test `packages/core/tests/test_storage_factory.py` (nuovo o append a quello esistente).

**Interfaces:** `storage_from_settings(settings, *, session: Session | None = None) -> DocumentStorage`. Con `gdrive` + service account → `GDriveStorage.from_service_account(...)` (invariato). Con `gdrive` senza service account → richiede `session`; cerca l'account Drive `active` con `storage_folder_id` non nullo (`DriveRepository(session).storage_account()` — nuovo metodo: al più uno, l'installazione è single-tenant); costruisce `UserTokens` + `DriveTransport` + `GDriveStorage(transport=..., root_folder_id=storage_folder_id)`. Se non c'è → `StorageNotConfigured` (nuova eccezione `DomainError` con il testo guidato) sollevata **alla prima `put`**, non alla costruzione: l'API deve partire anche prima che il titolare colleghi Drive. Implementato con `LazyUserDriveStorage(session_factory)` che risolve l'account alla prima operazione e lo ricontrolla se la riga cambia (`updated_at`).

- [ ] Test (RED): `storage_from_settings(gdrive, sa_json)` → `GDriveStorage` service account; `storage_from_settings(gdrive, no sa, session)` con account Drive e `storage_folder_id` → `put` scrive sul `FakeDrive` con `Authorization: Bearer <token utente>` sotto `<storage_folder_id>/<cliente>/...`; senza account → `put` solleva `StorageNotConfigured` e l'API (`apps/api/tests`) risponde 409 con il testo guidato; `get` idem.
- [ ] Implementare; verde; commit `feat(storage): Drive storage on the owner's own credential when there is no service account (slice 9 §4.3)`.

---

### Task 2: Le dipendenze dell'API e dell'MCP passano la sessione alla fabbrica

**Files:** `apps/api/src/pigrocrm_api/deps.py` (`StorageDep`), `apps/mcp/src/pigrocrm_mcp/__main__.py` e `server.py` (costruzione dello storage), test `apps/api/tests/test_documents_api.py` (append), `apps/mcp/tests/test_mcp_documents.py` (append).

**Interfaces:** `StorageDep` costruisce lo storage per richiesta con la `SessionDep` corrente quando il backend è `gdrive` senza service account (costo: una query leggera per richiesta sui soli endpoint che toccano lo storage; accettato). MCP: `build_server(..., storage=None)` → la fabbrica con `session_provider`.

- [ ] Test (RED): con settings `gdrive` senza service account e account Drive seminato, `POST /api/documents/from-template` scrive sul fake e `GET /download` rilegge identico; via MCP `create_document_from_template` idem.
- [ ] Implementare; verde; commit `feat(api,mcp): storage resolved per session so the owner's Drive is the document store`.

---

### Task 3: `set_roots` verifica la cartella di scrittura

**Files:** `packages/core/src/pigrocrm/core/drive/account.py` (`set_roots` chiama `verify_root_accessible` sulla `storage_folder_id` con il token utente), test `packages/core/tests/test_drive_oauth.py` (append).

- [ ] Test (RED): `set_roots` con `storage_folder_id` che il fake non conosce → `ValidationFailed` che nomina la cartella; con una cartella esistente → salvata; `root_folder_ids` non vengono verificati (lettura, si verificano all'uso).
- [ ] Implementare (`GoogleDriveAccountService` riceve un `transport_factory` opzionale per i test); verde; commit `feat(drive): choosing the write folder proves it is writable`.

---

### Task 4: Attivazione sull'installazione

**Files:** `docs/superpowers/notes/2026-09-04-drive-storage-runbook.md`.

Passi: `PIGROCRM_STORAGE_BACKEND=gdrive` in `.env` (senza service account), restart API, Impostazioni → Drive → collega, scegli la cartella `PigroCRM` (creata a mano su Drive) come cartella di scrittura e `Offerte`, `Fatture`, `Progetti` come radici di lettura; prova: `create_document_from_template` con «Rapporto ore» su un deal e verifica che il PDF compaia in `PigroCRM/<cliente>/...`; poi import dei 14 PDF di `Fatture` con `import_drive_file` e ricollegamento con `pdf_sorgente.drive_file_id` (9A/9C).

- [ ] Scrivere e committare — `docs: runbook to move the document store to the owner's Drive`.

---

## Self-review

- §4.3 (scrive il CRM, non l'agente; una cartella per cliente; nessuna migrazione dei byte) → T1, T2, T4. §5.4 (token utente sullo stesso trasporto) → T1. §6 → nessun tool nuovo, nessuna cancellazione aggiuntiva.
- Nomi coerenti con 9B: `DriveRepository.storage_account`, `UserTokens`, `DriveTransport`, `GDriveStorage(transport=, root_folder_id=)`, `GDriveStorage.from_service_account`, `storage_folder_id`, `set_roots`.
