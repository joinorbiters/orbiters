```{=typst}
#let muted = rgb("#465362")
#let divider = rgb("#E2E2E2")

#align(center)[
  #block(
    fill: rgb("#F9DC5C"),
    inset: 8pt,
    radius: 4pt,
    width: 100%,
  )[
    #align(center)[#text(size: 11pt, weight: "bold")[FATTURA PROFORMA - NON COSTITUISCE FATTURA]]
  ]
]

#v(12pt)

#text(size: 9pt, fill: muted)[{{fattura.etichetta}}] | #text(size: 9pt, fill: muted)[Numero: {{fattura.numero}}] | #text(size: 9pt, fill: muted)[Data: {{fattura.data}}]
{{#if fattura.periodo_competenza}}

#text(size: 9pt, fill: muted)[Periodo di competenza: {{fattura.periodo_competenza}}]
{{/if}}

#v(10pt)

#text(size: 9pt, weight: "bold", fill: muted)[Committente]
#stack(
  spacing: 2pt,
  [#text(size: 9pt)[{{cliente.ragione_sociale}}]],
  [#text(size: 9pt)[P.IVA: {{cliente.partita_iva}} | CF: {{cliente.codice_fiscale}}]],
  [#text(size: 9pt)[{{cliente.indirizzo_display}}]],
  [#text(size: 9pt)[PEC: {{cliente.pec}} | Codice destinatario: {{cliente.codice_destinatario}}]],
)

#v(14pt)
#text(size: 9pt, weight: "bold", fill: muted)[Dettaglio]
#table(
  columns: (0.46fr, 0.1fr, 0.14fr, 0.1fr, 0.2fr),
  align: (left, right, right, center, right),
  inset: (x: 4pt, y: 6pt),
  stroke: none,
  table.header(
    [#text(size: 8pt, weight: "bold", fill: muted)[DESCRIZIONE]],
    [#text(size: 8pt, weight: "bold", fill: muted)[QTA]],
    [#text(size: 8pt, weight: "bold", fill: muted)[PREZZO]],
    [#text(size: 8pt, weight: "bold", fill: muted)[%IVA]],
    [#text(size: 8pt, weight: "bold", fill: muted)[TOTALE]],
  ),
  {{#each righe}}[#text(size: 9pt)[{{descrizione}}]], [#text(size: 9pt)[{{quantita}}]], [#text(size: 9pt)[{{prezzo_unitario}}]], [#text(size: 9pt)[{{aliquota_iva}}]], [#text(size: 9pt)[{{prezzo_totale}}]],{{/each}}
)

#v(10pt)
#align(right)[
  #table(
    columns: (auto, auto),
    align: (left, right),
    inset: (x: 4pt, y: 4pt),
    stroke: none,
    [#text(size: 9pt, fill: muted)[Imponibile]], [#text(size: 9pt)[{{fattura.imponibile}}]],
    [#text(size: 9pt, fill: muted)[Imposta]], [#text(size: 9pt)[{{fattura.imposta}}]],
    [#text(size: 10pt, weight: "bold")[Totale documento]], [#text(size: 10pt, weight: "bold")[{{fattura.totale}}]],
  )
]

#v(14pt)
#text(size: 9pt, weight: "bold", fill: muted)[Modalita pagamento]
#table(
  columns: (0.2fr, 0.44fr, 0.16fr, 0.2fr),
  align: (left, left, center, right),
  inset: (x: 4pt, y: 6pt),
  stroke: none,
  table.header(
    [#text(size: 8pt, weight: "bold", fill: muted)[MODALITA]],
    [#text(size: 8pt, weight: "bold", fill: muted)[IBAN]],
    [#text(size: 8pt, weight: "bold", fill: muted)[SCADENZA]],
    [#text(size: 8pt, weight: "bold", fill: muted)[IMPORTO]],
  ),
  [#text(size: 9pt)[{{fiscale.modalita_pagamento}}]],
  [#text(size: 9pt)[{{fiscale.iban}}]],
  [#text(size: 9pt)[{{fattura.data_scadenza}}]],
  [#text(size: 9pt)[{{fattura.totale}}]],
)

#v(14pt)
#line(length: 100%, stroke: 0.6pt + divider)
#v(10pt)

#text(size: 8pt, fill: muted)[{{fattura.dichiarazione_regime}}]

#text(size: 8pt, fill: muted)[{{fattura.dichiarazione_bollo}}]
```
