# Revisione UI dell'app: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** L'app (`apps/web`) assume la struttura del riferimento: sidebar scura con ricerca globale e sotto-menu, contenuto in un pannello arrotondato, intestazioni di pagina con azione primaria, tab a sottolineatura, tabelle con pillole di stato e menu «⋯», bottoni e card morbidi. Colori invariati.

**Architecture:** tutto passa dai token e dalle primitive shadcn (`src/styles/tokens.css`, `src/components/ui/*`), più tre componenti condivisi nuovi (`PageHeader`, `StatusPill`, `RowActions`) e la riscrittura di `AppShell`/`AppHeader`. Le pagine cambiano solo per adottare i componenti condivisi. La landing e Orbiters non cambiano.

**Tech Stack:** React 19, TanStack Router/Query/Table v9, Tailwind v4 (`@theme` in tokens.css), shadcn, lucide-react, vitest + testing-library.

**Spec:** `docs/superpowers/specs/2026-09-08-ui-revision-design.md`

## Global Constraints

- Nessun colore nuovo: solo le cinque tinte della palette e i loro `color-mix()` verso `#ffffff` (enforced da `src/styles/tokens.test.ts`, che va aggiornato ai nuovi valori, non allentato).
- Landing e Orbiters (`apps/web/landing/*`, `landing.css`, `orbiters.css`, `system.css`) non si toccano; i loro test restano verdi.
- Testi italiani, sentence case; niente maiuscole salvo le intestazioni di tabella.
- Ogni componente toccato resta coperto da vitest; `npm run lint` e `npx tsc --noEmit` puliti prima di ogni commit.
- Commit con `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; nel worktree condiviso si committa con `git commit -- <paths>`.

---

### Task 1: Token e primitive

**Files:** `src/styles/tokens.css`, `src/styles/tokens.test.ts`, `src/components/ui/{button,badge,card,tabs,table,input,select,dialog,dropdown-menu}.tsx`.

**Interfaces:** `--radius: 10px`; `--border` 12%; ombre morbide `--shadow-sm/md/lg`; `--sidebar*` sul Prussian Blue; `Card` senza ombra a gradino; `Badge` variante `pill` (rounded-full, punto colorato opzionale via prop `dot`); `Tabs` a sottolineatura (`TabsList` trasparente con bordo inferiore, `TabsTrigger` con `data-[state=active]:border-b-2`); `Table` con intestazioni 12px Charcoal e righe alte 56px.

- [ ] Test (RED): tokens.test.ts asserisce i nuovi valori; test di rendering delle varianti nuove.
- [ ] Implementare; verde; commit `style(web): soft shapes — radius, borders, shadows and the primitives that read them`.

### Task 2: Shell

**Files:** `src/components/AppShell.tsx` (+test), `src/components/AppHeader.tsx` → rinominato/ridotto a `PageHeader.tsx` (+test), `src/routes/app.tsx` se il pannello va montato lì.

**Interfaces:** `AppShell` rende la sidebar scura (brand + campo ricerca che apre `CommandPalette`, nav a gruppi espandibili con `aria-expanded`, blocco utente in fondo) e il pannello contenuto (Paper fuori, bianco dentro, raggio 16). `PageHeader({ icon, title, actions?, tabs? })` esportato da `src/components/PageHeader.tsx`; le pagine lo usano al posto dell'`<header>` locale. Gruppi: «Vendite» (Clienti, Persone, Deal), «Amministrazione» (Fatture, Solleciti, Ore, Costi), «Analisi», «Impostazioni» (le voci di `SettingsLayout`). Lo stato aperto/chiuso dei gruppi in `localStorage`, gruppo del percorso corrente sempre aperto.

- [ ] Test (RED): ricerca apre la palette; gruppo attivo aperto; sotto-voce evidenziata; collasso.
- [ ] Implementare; verde; commit `feat(web): dark sidebar with global search and groups, content in a panel`.

### Task 3: Tabelle e azioni

**Files:** `src/components/DataTable.tsx` (+test), nuovi `src/components/StatusPill.tsx`, `src/components/RowActions.tsx` (+test), `src/features/{invoices,customers,people,deals,costs}/columns.tsx` (+test).

**Interfaces:** `StatusPill({ tone: 'ink'|'muted'|'accent'|'danger'|'gold', children })`; `RowActions({ items: {label, onSelect, destructive?}[] })` = bottone «⋯» `aria-label="Azioni"` + `DropdownMenu`. Le colonne stato usano `StatusPill`; le date usano l'icona `Calendar`; le azioni in riga oggi rese come bottoni migrano in `RowActions`.

- [ ] Test (RED) per i due componenti e per una colonna per feature.
- [ ] Implementare; verde; commit `feat(web): tables with status pills, dated cells and a row actions menu`.

### Task 4: Pagine

**Files:** `src/routes/app/{index,clienti/index,persone/index,deal/index,fatture/index,ore,solleciti,analisi,impostazioni}.tsx`, `src/features/dashboard/DashboardPage.tsx`, `src/features/settings/SettingsLayout.tsx`, `src/features/analytics/AnalyticsLayout.tsx`, `src/components/EntityDetailLayout.tsx`.

**Interfaces:** ogni pagina apre con `PageHeader`; le liste hanno la riga filtri (chip `rounded-full` per gli stati già esistenti, ricerca, select) sopra la `DataTable`; le tab di Impostazioni/Analisi/dettaglio usano le `Tabs` a sottolineatura; la dashboard usa le card KPI a 3 colonne.

- [ ] Test (RED): i test di pagina esistenti aggiornati (titolo via PageHeader, azione primaria presente).
- [ ] Implementare; verde; commit `feat(web): every page opens with a header and its primary action`.

### Task 5: Controllo visivo

**Files:** `docs/superpowers/notes/2026-09-08-ui-revision-screenshots.md` + PNG in `.playwright-mcp/` (non committati).

- [ ] Screenshot di Home, Clienti, Fatture, Impostazioni a 1440 e 390px; confronto con il riferimento; correzioni minute (spaziature, troncamenti) in un commit `style(web): ...`.

## Self-review

- Spec §3 → T1; §4 sidebar/pannello/intestazione → T2; §4 tabella/azioni → T3; §4 tab/filtri/card e §5 → T4; §6 → tutti i task + T5.
- Nomi coerenti: `PageHeader`, `StatusPill`, `RowActions`, `--radius`, `--border`, `--sidebar`.
