{{offerta.data}}

Spett.le

**{{cliente.ragione_sociale}}**

{{cliente.indirizzo}}

{{cliente.partita_iva}}

Referente: {{referente.nome}}
Email: {{referente.email}}

**Oggetto: {{offerta.oggetto}}**

Facendo seguito ai recenti contatti fra noi intercorsi, siamo lieti di sottoporVi la presente proposta (di seguito la “Proposta”) di conferimento d’incarico per la prestazione di servizi professionali. Nel seguito di questa Proposta, inclusa ogni sua appendice, tabella e/o allegato, saranno utilizzate le seguenti definizioni oltre che le definizioni contenute alle Condizioni Generali allegate:

- “Fornitore”: {{emittente.ragione_sociale}}

- “Cliente”: {{cliente.ragione_sociale}}

1.  **Ambito del progetto e obiettivi**

> {{offerta.ambito}}


2.  **Attività del progetto**

> {{offerta.attivita}}

3.  **Esclusioni**

Non costituisce oggetto della presente proposta ogni altra attività, non espressamente indicata nel presente documento.

4.  **Condizioni economiche**

Per le attività sopra descritte, {{emittente.ragione_sociale}} propone i seguenti elementi di costo:

```{=typst}
#table(
  columns: (0.8fr, 0.2fr),
  align: (auto, center),
  stroke: none,
  table.header([#strong[Servizio/Attività]], [#strong[Totale]]),
  {{#each offerta.righe}}[{{servizio}}], [{{totale}}],{{/each}}
)
```

{{emittente.regime_fiscale}}

5.  **Modalità di fatturazione e pagamento**

La fatturazione delle attività sopra riportate averrà alle seguenti condizioni:

{{offerta.pagamento}}


6.  **Privacy**

Il trattamento dei dati personali avverrà nel rispetto della normativa vigente. L’informativa completa e le eventuali nomine necessarie saranno fornite da {{emittente.ragione_sociale}} prima dell’avvio delle attività o su richiesta.

7.  **Condizioni Generali di Fornitura Software**

Le condizioni generali applicabili alla presente fornitura possono essere riassunte come segue:

- Ambito e variazioni: {{emittente.ragione_sociale}} svolge le attività descritte in questa Proposta. Ogni estensione o modifica richiede conferma scritta e può comportare una revisione di tempi e costi.

- Collaborazione del Cliente: Il Cliente fornisce accessi, materiali, approvazioni e feedback necessari; eventuali ritardi possono incidere sulle tempistiche.

- Consegne e verifiche: i deliverable sono consegnati secondo il piano concordato; eventuali correzioni vengono gestite e chiuse con accordo reciproco.

- Proprietà intellettuale: {{emittente.ragione_sociale}} mantiene la titolarità di metodi, componenti riusabili e know-how; Il Cliente ottiene il diritto d’uso dei deliverable per le finalità del progetto.

- Pagamenti: valgono le scadenze e le modalità indicate nella sezione “Modalità di fatturazione e pagamento”.

- Riservatezza: le Parti mantengono riservate le informazioni ricevute e le utilizzano solo per l’esecuzione del progetto, salvo diversi accordi intercorsi.

- Responsabilità e limiti: {{emittente.ragione_sociale}} risponde per le attività svolte in conformità; non risponde per malfunzionamenti dovuti a terzi o a uso improprio.

- Sospensione o risoluzione: in caso di inadempimenti gravi o mancati pagamenti, {{emittente.ragione_sociale}} può sospendere le attività; restano dovute le prestazioni già erogate.

8.  **Validità della proposta**

Vi preghiamo di restituirci la Presente Proposta da Voi sottoscritta per accettazione entro il termine di 15 gg dalla data di presentazione di questa offerta. Successivamente a tale data la Proposta si intenderà revocata e priva di effetto, salvo diversa indicazione di {{emittente.ragione_sociale}}.

\* \* \* \* \* \* \*

Lieti di avere avuto l’opportunità di offrire i nostri Servizi e confidando di poter cooperare con Voi, restiamo in attesa di un Vostro cortese riscontro, che riceverà da parte nostra la massima attenzione.

Cordialità

{{emittente.ragione_sociale}}


![](./media/sign_is.png){ width=90pt }

{{offerta.data}}

Per conoscenza e accettazione:

**Il Cliente**
\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_
