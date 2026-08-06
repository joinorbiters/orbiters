# PigroCRM

> Il CRM che lavora al posto tuo.

CRM **AI-first** per freelancer, consulenti e piccole startup italiane. Ogni operazione disponibile
nell'interfaccia web è accessibile anche via REST API e via **MCP** (Model Context Protocol),
così un agente come Claude può fare tutto ciò che fai tu.

Copre l'intero ciclo senza cambiare applicazione:

```
Contatto → Cliente → Deal → Offerta → Lavoro → Time Tracking → Fattura → Analisi economica
```

## Principi

- **Lean by default** — ogni funzionalità è usabile senza configurazione; le personalizzazioni sono opzionali.
- **API first** — la UI usa esclusivamente le API pubbliche. Nessuna logica esiste solo nel frontend.
- **MCP first** — il server MCP non è un adattatore aggiunto dopo: usa gli stessi servizi della UI, in-process.
- **Nessuna duplicazione** — ogni dato è salvato una volta sola.

## Stack

| | |
|---|---|
| Backend | Python · FastAPI · SQLAlchemy · Alembic |
| Database | PostgreSQL |
| Frontend | Vite · React · TypeScript · TanStack Router · shadcn/ui (Tailwind + Radix) |
| Documenti | Pandoc + Typst |
| Deploy | Docker Compose · nginx · GitHub Actions |

## Stato

In sviluppo. Sostituirà [the previous system](https://example.com).

Le specifiche sono in [`docs/superpowers/specs/`](docs/superpowers/specs/).
