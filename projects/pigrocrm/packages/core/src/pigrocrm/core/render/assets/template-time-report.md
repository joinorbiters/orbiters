<!-- packages/core/src/pigrocrm/core/render/assets/template-time-report.md

The layout carried over from `.reference-acme/offer/template-time-tracking.typ`. What
is carried is the knowledge: the "Periodo / Data emissione" line, the Cliente + Offerta
block, a three-column DATA · ORE · DESCRIZIONE table with the description at 0.7fr
because it is the only column the client actually reads, the thin divider, and a footer
pairing the total hours with the **entry count** -- the detail that makes the document
verifiable at a glance.

What is deliberately NOT carried is the identity block Acme drew inline as its first
`#grid` with `header: none`. This product renders `header.typ.template` from
`emitter_profile` through `--include-in-header` for every document, and that header
already places the logo left and the issuer's identity right. Redrawing it here would
put it on the page twice.

Also not carried: `[ENTRIES_PLACEHOLDER]`, which Acme filled by concatenating Typst
source in JavaScript. It is `{{#each voci}}` here, so every value passes through
`escape_for` exactly once, in the context it lands in.
-->

```{=typst}
#v(0.4cm)
#text(size: 16pt, weight: "bold")[Rapporto ore]
#v(0.15cm)
#text(size: 9pt)[Periodo: {{periodo}} · Data emissione: {{oggi}}]
#v(0.35cm)
#line(length: 100%, stroke: 0.6pt + luma(180))
#v(0.35cm)
#grid(
  columns: (1fr, 1fr),
  column-gutter: 0.6cm,
  [
    #text(size: 8pt, fill: luma(110))[CLIENTE] \
    #text(size: 10pt, weight: "bold")[{{cliente.ragione_sociale}}] \
    #text(size: 9pt)[{{cliente.partita_iva}}]
  ],
  [
    #text(size: 8pt, fill: luma(110))[OFFERTA] \
    #text(size: 10pt, weight: "bold")[{{deal.nome}}]
  ],
)
#v(0.5cm)
#table(
  columns: (0.18fr, 0.12fr, 0.7fr),
  align: (left, right, left),
  stroke: none,
  table.header(
    [#text(size: 8pt, fill: luma(110))[DATA]],
    [#text(size: 8pt, fill: luma(110))[ORE]],
    [#text(size: 8pt, fill: luma(110))[DESCRIZIONE]],
  ),
  {{#each voci}}[{{data}}], [{{ore}}], [{{descrizione}}],{{/each}}
)
#v(0.35cm)
#line(length: 100%, stroke: 0.6pt + luma(180))
#v(0.25cm)
#grid(
  columns: (1fr, auto),
  [#text(size: 9pt, fill: luma(110))[{{numero_voci}} voci]],
  [#text(size: 11pt, weight: "bold")[Totale ore: {{totale_ore}}]],
)
```
