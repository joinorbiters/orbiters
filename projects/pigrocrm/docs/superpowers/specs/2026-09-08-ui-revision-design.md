# Revisione UI dell'app — design

**Data:** 2026-09-08
**Ambito:** `apps/web` (l'app, non la landing). Struttura della shell, primitive shadcn, tabelle,
tab, intestazioni di pagina e azioni. I colori non cambiano.

## 1. Il brief

Ivan ha portato tre schermate di riferimento (un prodotto di value-based billing: home con
saluto e KPI, lista clienti, "Value studio" con tab e tabella) e chiesto di avvicinare
PigroCRM a quel modo di stare in pagina: menu scuro a sinistra con la ricerca globale in
alto, contenuto in un pannello arrotondato staccato dal menu, bottoni e box morbidi, tabelle
con righe alte e stati a pillola, sotto-menu nel menu laterale, tab a sottolineatura, azioni
di riga in un menu «⋯». Vincolo esplicito: **i colori restano quelli di adesso**.

## 2. Cosa si tiene e cosa cambia

Si tiene: la palette (Prussian Blue `#011936`, Charcoal Blue `#465362`, Paper `#f1f2f3`,
Watermelon `#ed254e`/`#e5133e`, Royal Gold `#f9dc5c`), il font Outfit, la griglia di token in
`src/styles/tokens.css`, i componenti shadcn, TanStack Router/Table, i testi.

Cambia il sistema di forme. Dal 2026-09-07 l'app condivideva con Orbiters «bordi netti, ombra
a gradino, raggio zero» (spec Orbiters §7). Questa revisione lo sostituisce nell'**app**, non
nella landing né in Orbiters, che restano a pixel: un prodotto da usare otto ore al giorno
guadagna dalle forme morbide del riferimento, una landing da guardare cinque secondi no.
`landing.css`, `orbiters.css`, `system.css` e i loro test non si toccano.

## 3. Token

| Token | Prima | Dopo | Perché |
|---|---|---|---|
| `--radius` | `0px` | `10px` | il riferimento è arrotondato ovunque; 10px tiene i bottoni a 10 e le card a 14 tramite le derivate shadcn |
| `--shadow-*` | spostamenti interi, niente sfocatura | ombre morbide a bassa opacità dell'inchiostro (`0 1px 2px` / `0 8px 24px` di `--color-prussian-blue` al 6–12%) | il gradino appartiene al sistema a pixel |
| `--border` | inchiostro al 24% | inchiostro al **12%** | il riferimento separa con linee quasi invisibili e con lo spazio |
| card | `ring-1 ring-border shadow-[4px_4px_0_0_var(--border)]` | `border border-border bg-card`, nessuna ombra | le card stanno sulla pagina, non fluttuano |
| `--sidebar` | `--card` (bianca) | `--color-prussian-blue`; testo Paper; voce attiva `white/10`; hover `white/6` | il menu scuro è il tratto più riconoscibile del riferimento e Prussian Blue è già nella palette |
| `--sidebar-primary` | Watermelon | Watermelon-strong | resta l'unico accento; il contrasto con il bianco passa |
| griglia sul `body` | linee al 7% | **rimossa** nell'app | il pannello bianco copre tutto; la griglia era il legame con Orbiters |

Nessun colore nuovo. I verdi/rossi delle variazioni percentuali del riferimento non entrano:
gli scostamenti positivi usano Prussian Blue su Paper, quelli negativi Watermelon al 10% di
fondo, come già fa il badge `destructive`.

## 4. Layout

```
┌──────────────┬────────────────────────────────────────────────────────┐
│ ▣ PigroCRM ⌘K│ paper (#f1f2f3), padding 12px                          │
│ [🔍 Cerca  ] │ ┌────────────────────────────────────────────────────┐ │
│              │ │ pannello bianco, raggio 16, bordo 12%              │ │
│ ⌂ Home       │ │ ┌ icona ┐ Titolo pagina            [+ Azione ▾] ○ │ │
│ ∿ Analisi    │ │ ── tab ── tab ── tab ─────────────────────────────  │ │
│ ⚇ Clienti    │ │ [Tutte] [Bozze] [Emesse]   🔍 [Periodo ▾] [≡|▦]     │ │
│ ✦ Deal       │ │ ┌──────────────────────────────────────────────┐   │ │
│ ▤ Vendite  ⌄ │ │ │ CLIENTE     STATO     TOTALE    DATA      ⋯ │   │ │
│   Fatture    │ │ │ ● Acme   ● Emessa  6.510 €   3 ago 2026 ⋯│   │ │
│   Solleciti  │ │ └──────────────────────────────────────────────┘   │ │
│   Ore        │ │                                                    │ │
│ ⚙ Impost.  ⌄ │ └────────────────────────────────────────────────────┘ │
│              │                                                        │
│ ● Ivan Sala ⌃│                                                        │
└──────────────┴────────────────────────────────────────────────────────┘
```

- **Sidebar** 272px, Prussian Blue, ricerca globale come campo in alto (apre la
  `CommandPalette` esistente; mostra `⌘K`), voci con icona Lucide 16px; i gruppi
  («Vendite», «Impostazioni») sono espandibili con le sotto-voci rientrate e una linea
  verticale a sinistra come nel riferimento; in fondo il blocco utente (avatar iniziali,
  nome, spazio) con il menu esistente. Collassabile come oggi.
- **Pannello contenuto**: margine 12px su Paper, bianco, raggio 16, bordo 12%, scroll
  interno. Su schermi < 1024px il margine scende a 0 e il raggio a 0 (il pannello diventa la
  pagina).
- **Intestazione di pagina** (`PageHeader`): icona in un quadrato Paper 40px, titolo 24px
  semibold, a destra l'azione primaria (bottone pieno Watermelon-strong, `+ Crea`, con
  menu a tendina quando le azioni sono più di una) e l'avatar. Sotto, quando servono, le tab.
- **Tab**: sottolineatura 2px Prussian Blue sull'attiva, testo 15px, nessun riquadro.
- **Riga filtri**: chip a pillola («Tutte», «Bozze»…) a sinistra; a destra icona ricerca
  tonda, select con bordo 12% e raggio 10, eventuale toggle lista/griglia.
- **Tabella**: contenitore bianco con bordo 12% e raggio 14; intestazioni 12px, tracking
  leggero, Charcoal Blue; righe 56px; separatori 12%; hover Paper; prima colonna con
  avatar/iniziali dove c'è un'entità; stati come pillola con punto colorato; date con icona
  calendario; ultima colonna «⋯» che apre il `DropdownMenu` con le azioni che oggi sono
  bottoni in riga.
- **Bottoni**: primario pieno Watermelon-strong, testo bianco; secondario bordo 12% su
  bianco; ghost per le icone; tutti raggio 10, altezza 36 (sm 32). Le chip di filtro sono
  bottoni `rounded-full`.
- **Card KPI** (dashboard): etichetta 15px Charcoal, valore 30px semibold, badge di
  variazione a pillola, sottotitolo «vs periodo precedente». Griglia a 3.

## 5. Principi

1. Una sola cosa forte per schermata: l'azione primaria in alto a destra. Il resto è quieto.
2. Le linee separano solo dove serve; lo spazio fa il resto.
3. Nessun testo in maiuscolo nei contenuti; le intestazioni di tabella sono l'unica eccezione,
   come nel riferimento.
4. Niente animazioni d'ingresso; solo le transizioni delle azioni (menu, dialog, tab).
5. Tutto il testo in italiano, seconda persona, verbi al presente; i pulsanti dicono cosa fanno.

## 6. Verifica

- I test dei token (`src/styles/tokens.test.ts`) si aggiornano ai nuovi valori; i test della
  landing restano com'erano e devono restare verdi (la landing non cambia).
- Ogni componente toccato mantiene i test vitest; se ne aggiungono per `PageHeader`,
  `StatusPill`, il menu «⋯» e i gruppi espandibili della sidebar.
- Controllo visivo: screenshot Playwright di Home, Clienti, Fatture, Impostazioni a 1440 e
  a 390px di larghezza, confrontati con le tre schermate di riferimento.
- Accessibilità: focus visibile, contrasto ≥ 4.5:1 su testo (Paper su Prussian Blue nel menu
  passa), `aria-expanded` sui gruppi, `aria-label` sul bottone «⋯».
