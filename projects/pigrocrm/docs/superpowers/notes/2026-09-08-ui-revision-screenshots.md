# Controllo visivo della revisione UI (2026-09-08)

Task 5 della revisione UI (`docs/superpowers/specs/2026-09-08-ui-revision-design.md`, §4
per il layout, §6 per la verifica). Screenshot Playwright dell'app viva su
`http://localhost:5173/app/`, viewport impostata con `page.setViewportSize` e non
ridimensionando la finestra, così che sotto i 1024px si eserciti la struttura vera —
binario di icone più cassetto in sovrimpressione — e non solo una finestra più stretta.

I PNG stanno in `.playwright-mcp/ui-rev/` e **non sono committati**.

## Gli screenshot, uno per riga

**A 1440 × 900**

- `home-1440.png` — pannello bianco staccato su fondo Paper, intestazione con quadrato
  Paper da 40px e titolo da 24px, tab a sottolineatura «Commerciale / Economica», card
  KPI su griglia a 3 con la quarta sola in seconda riga (accettabile: §4 chiede la
  griglia a 3, non quattro card). Corretto in questo passaggio: i tre preselettori del
  periodo erano senza linea né fondo, e la voce «Home» del menu non risultava attiva.
- `clienti-1440.png` — riga di ricerca sotto l'intestazione, tabella con iniziali
  nella prima colonna, intestazioni 12px Charcoal, righe alte, em dash per i valori
  assenti. Corrisponde al riferimento senza correzioni.
- `fatture-1440.png` — chip a pillola («Tutte» attiva scura, poi gli stati), select dei
  tipi con bordo 12% e raggio 10, pillole di stato con il punto, icona calendario sulle
  date, totali allineati a destra, pillola di pagamento. È la schermata più vicina al
  riferimento.
- `deal-lista-1440.png` — intestazione con azione secondaria («Vista Kanban»), chip di
  filtro, campo di ricerca, tabella con nome più ragione sociale nella stessa cella.
- `impostazioni-1440.png` — tredici tab a sottolineatura su una riga, il gruppo
  «Impostazioni» aperto nel menu con la sotto-voce attiva, tabella dei campi vuota con il
  suo messaggio.
- `cliente-dettaglio-1440.png` — nome come titolo, «Cliente» come descrizione, due azioni
  in alto a destra (Modifica, Archivia), tab di dettaglio a sottolineatura, card con
  righe etichetta/valore separate da linee al 12%.

**A 390 × 844**

- `home-390.png` — il titolo «Home» era scomparso del tutto e il periodo usciva dal
  pannello a destra. Corretto: l'intestazione si impila e i due campi data possono
  restringersi.
- `clienti-390.png` — regge: una colonna visibile, ricerca a piena larghezza, righe
  leggibili. Il titolo era però «Cl…»: corretto.
- `fatture-390.png` — il caso peggiore: titolo «F…» e descrizione a una parola per riga
  per tutta l'altezza dello schermo. Corretto.
- `deal-lista-390.png` — titolo «D…», descrizione a una parola per riga, colonne della
  tabella oltre il bordo del pannello. Corretto.
- `impostazioni-390.png` — «+ Nuovo campo» tagliato fuori dal pannello, riga di tab
  troncata a metà di «Template», tabella oltre il bordo. Corretto.
- `drawer-390.png` — cassetto aperto sopra la pagina, con lo sfondo scurito, «Clienti»
  evidenziata dentro «Vendite» e «amministratore» sotto il nome: le tre cose sistemate
  nel primo commit si vedono qui.

## Valori CSS misurati sulla pagina viva

| Cosa | Atteso (spec) | Misurato |
|---|---|---|
| larghezza della sidebar a 1440 | 272px (§4) | **272px** |
| `--radius` | 10px (§3) | **10px** |
| `--border` | inchiostro al 12% (§3) | **`color-mix(in oklab, #011936 12%, #ffffff)`**, risolto in `oklab(0.905682 -0.00213339 -0.00746856)` |
| raggio del pannello | 16px (§4) | misurato **18px** (`rounded-2xl`, cioè il raggio derivato delle card) → **ora 16** |
| altezza di riga in `tbody` su Clienti a 1440 | 56px (§4) | **57px**, cioè 56 più il separatore da 1px: va bene |
| fondo del `body` | Paper `#f1f2f3` (§3) | **`rgb(241, 242, 243)`** |
| `--muted` | tinta della palette | era `#eef4f2` → **ora `#f1f2f3`**, cioè Paper |
| `--secondary` | tinta della palette | era `#e6ecea` → **ora `color-mix(in oklab, #465362 14%, #ffffff)`**, che il browser risolve in `oklab(0.921155 -0.00123556 -0.00395445)`: croma praticamente nulla, nessuna traccia di ciano |

## Le correzioni

### Primo commit (`81bba01`)

1. **`--muted` e `--secondary` erano tinte di ciano** (`#eef4f2`, `#e6ecea`), residui dei
   giorni in cui il fondo pagina era Mint Cream e fuori dalla palette. `--muted` diventa
   Paper — che è ciò che l'hover di riga deve essere (§4) — e `--secondary` una mescolanza
   di Charcoal Blue verso il bianco al 14%; in modo scuro entrambe diventano bianco
   mescolato nell'inchiostro, l'idioma che l'accento della sidebar usa già.
   `src/styles/tokens.test.ts` pretende ora che entrambe, in `:root` e in `.dark`, siano
   una tinta o una mescolanza di tinte, con `#ffffff` come unico esadecimale ammesso.
2. **L'hover della tabella era invisibile**: con `--muted` diventato Paper,
   `hover:bg-muted/40` sul bianco del pannello vale `#f9fafa`. L'hover è Paper piena, la
   riga selezionata sale a `--secondary`, e il `focus-visible` delle righe cliccabili
   segue la stessa tinta.
3. **Il pannello era arrotondato a 18** invece che a 16.
4. **La voce attiva del menu si spegneva appena l'URL portava parametri di ricerca**:
   `activeOptions` non diceva `includeSearch: false`, che in TanStack è vero per difetto,
   quindi sulla Home — dove la dashboard scrive tab e periodo nell'URL al caricamento —
   «Home» non era mai evidenziata.
5. **I tre preselettori del periodo non sembravano premibili** (erano `ghost`): ora
   `outline`, con i campi data al raggio 10.
6. **`PIGROCRM_TOKEN` aveva perso il monospazio**: la descrizione di `PageHeader` è una
   stringa semplice, e la frase è tornata un paragrafo del corpo con il suo `<code>`.
7. **La revoca di un token era un `Trash2` in riga**: è passata in `RowActions` come voce
   distruttiva del menu «⋯»; un token già revocato non mostra alcun «⋯».
8. **`role="search"` non aveva nome**: ora `aria-label="Ricerca globale"`.
9. **Sotto il nome nel menu compariva `admin`**, il valore memorizzato dall'API:
   `src/lib/roles.ts` tiene ora l'unica mappa dei ruoli in italiano.

### Secondo commit (questo passaggio, dai PNG a 390)

10. **L'intestazione di pagina si impila sotto `md`.** A 390 icona, titolo da 24px e
    bottone primario non stanno su una riga: il titolo veniva troncato a «F…», «D…»,
    «Cl…» e la descrizione andava a una parola per riga, perché le azioni tenevano la
    loro larghezza e il testo accanto cedeva tutta la propria. Ora `flex-col md:flex-row`:
    icona e titolo su una riga a piena larghezza (nessun `truncate` sotto `md`),
    descrizione sotto, azioni su una riga propria con `flex-wrap`. Da `md` in su la riga
    unica di prima, `truncate` compreso.
11. **La riga di tab scorre dentro il pannello** (`overflow-x-auto`): tredici tab delle
    impostazioni sono più larghe di un telefono, e l'alternativa era la pagina che
    scorreva di lato con «Template» tagliato a metà.
12. **La tabella scorre dentro la propria scatola.** Il contenitore del `DataTable` passa
    da `overflow-hidden` a `overflow-x-auto overflow-y-hidden`: il taglio verticale
    tiene l'hover della prima riga dentro gli angoli arrotondati, l'asse orizzontale
    diventa un asse di scorrimento, e le colonne di Deal e dei pannelli delle
    impostazioni non arrivano più oltre il bordo del pannello.
13. **I due campi data possono restringersi** (`min-w-0`): la riga del periodo già
    andava a capo, ma un `input[type=date]` non scende sotto la propria larghezza
    intrinseca se non gli si dice che può.
14. **La barra del pannello «Campi» va a capo** (`flex-wrap`): il select dell'entità
    (224px) e «+ Nuovo campo» non stavano su una riga, e il bottone finiva fuori dal
    pannello.

Ogni voce di questo secondo gruppo ha il suo test scritto prima
(`PageHeader.test.tsx`, `DataTable.test.tsx`, `DashboardPage.test.tsx`,
`FieldsPanel.test.tsx`): asserzioni sulle classi e non sugli stili calcolati, perché
jsdom non carica il foglio di stile e non impagina nulla, e quelle classi sono
esattamente ciò che il controllo Playwright rilegge.

## Le due decisioni che restano a Ivan

1. **Sotto il nome, nel blocco utente in fondo al menu, §4 vuole lo spazio, non il
   ruolo.** Scrivere «amministratore» invece di `admin` è la correzione minima e onesta
   di quello che c'è; il dato giusto è il nome dello spazio, e mostrarlo richiede una
   lettura in più. Da decidere se vale.
2. **L'avviso del consenso Google occupa il bordo superiore del pannello, sopra
   l'intestazione, su ogni schermata.** A 390 si mangia un sesto dello schermo ed è la
   prima cosa che si legge sulla Home. Non è stato toccato di proposito: dove va (lì, in
   un banner più compatto, o dentro «Impostazioni → Gmail» con un solo segnale altrove)
   è una scelta di prodotto.

## Da guardare al prossimo passaggio

- Le altre tab delle impostazioni a 390 non sono state fotografate: «Utenti» e
  «Pipeline» hanno una barra di titolo più bottone dello stesso tipo di quella di
  «Campi», che a 390 non esce dal pannello ma stringe il paragrafo. Vanno guardate con
  uno screenshot prima di toccarle.
- Le pagine Persone, Ore, Solleciti, Analisi e Documenti non sono in questo giro.

## Dopo le correzioni

Il giro a 390 è stato rieseguito su `8b6abe7`, cioè *dopo* le quattordici correzioni
sopra, sulle quattro pagine che la spec §6 nomina (Home, Fatture, Impostazioni) più Deal
lista, che è quella con più colonne e quindi il caso peggiore per la tabella:

| Pagina | File |
|---|---|
| Home | `.playwright-mcp/ui-rev/home-390-v2.png` |
| Fatture | `.playwright-mcp/ui-rev/fatture-390-v2.png` |
| Deal lista | `.playwright-mcp/ui-rev/deal-lista-390-v2.png` |
| Impostazioni | `.playwright-mcp/ui-rev/impostazioni-390-v2.png` |

**La misura che chiude il ciclo:** su tutte e quattro `document.scrollWidth` vale **390**,
uguale al viewport. È il numero che dimostra le correzioni 9–14 tutte insieme: nessuna
pagina sfonda più di lato, quindi né l'intestazione, né la riga di tab, né la tabella, né
i campi data, né la barra di «Campi» spingono il documento oltre lo schermo. Prima delle
correzioni era quello a sfondare, ed era il difetto per cui l'intera pagina scorreva
invece del solo elemento troppo largo.

I PNG stanno, come i precedenti, in `.playwright-mcp/` e non sono committati: il fatto
verificabile che resta scritto qui è la misura, non l'immagine.

**Cosa questo giro non ha fotografato**, detto per chiarezza e non implicito: **Persone,
Ore, Solleciti, Analisi e Documenti** non sono state riprese, né prima né dopo — di
nessuna delle due esiste uno screenshot a nessuna larghezza. Restano coperte solo dai
test sulle classi, e vanno guardate al prossimo passaggio insieme alle altre tab delle
impostazioni.
