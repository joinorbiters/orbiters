"""invoices.importata_da: any legacy provenance value becomes 'esterno'

Revision ID: 0029
Revises: 0028

A data migration and nothing else: the column keeps its type and its nullability, and
only the fourteen rows slice 9 imported change value -- plus the `imported` activity
each of them wrote, which copied the same value into its JSONB payload.

`importata_da` is read back by `InvoiceRead`, so it travels to the API, to MCP and to
the web client, where it used to be printed as the name of the tool the invoices came
out of. That name is the owner's business and no part of this CRM's copy: what the
register needs to say is that a document was issued outside -- which is why there is no
XML and no PDF pigroCRM produced -- and `'esterno'` says exactly that and no more.
Renaming the `Literal` in `invoices/schemas.py` without moving the rows would leave
those fourteen holding a value no schema admits, still handed to every client.

Scoped by value, and deliberately without naming the value it replaces: any row whose
provenance is neither NULL nor `'esterno'` is a row this migration is about. Matching on
`<> 'esterno'` rather than on one literal does the same thing to the data that matching
the old name did, and does it for any other legacy spelling that may exist in a database
older than this one, while leaving every `NULL` untouched -- `NULL` means "pigroCRM
issued this itself", which is a different fact and must survive.

The downgrade is a no-op, and that is a decision rather than an omission. It used to put
the old literal back, for the sake of a database rolled back to 0028 and read by code
that knew only that literal. That literal no longer exists anywhere in this repository,
so a downgrade cannot restore it without reintroducing exactly what the migration exists
to remove. Dropping to `NULL` instead would be worse than either: `NULL` says pigroCRM
issued the document, which for these rows is false and would put fourteen invoices back
in reach of `export_invoice_xml` and of a PDF regeneration. So the column keeps
`'esterno'` across a rollback, and code at 0028 reading it sees a provenance it does not
recognise rather than a document it wrongly believes it produced.

The `activities` half matters for the same reason the column does, and is not covered by
it: `import_issued` records `{anno, numero, totale, importata_da}` (invoices/service.py),
`ActivityRead` hands the payload to the client whole, and the web timeline dumps the
keys it has no special rendering for. So a payload left alone would keep printing the
old name on the invoice's own timeline even after the column stopped saying it. Scoped
on the payload value rather than on `kind` alone -- `jsonb_set` on a payload that has no
such key would *add* one -- and `kind` is still in the predicate so the statement reads
as what it is: the import's own event.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE invoices
           SET importata_da = 'esterno'
         WHERE importata_da IS NOT NULL
           AND importata_da <> 'esterno'
        """
    )
    op.execute(
        """
        UPDATE activities
           SET payload = jsonb_set(payload, '{importata_da}', '"esterno"'::jsonb)
         WHERE kind = 'imported'
           AND payload->>'importata_da' IS NOT NULL
           AND payload->>'importata_da' <> 'esterno'
        """
    )


def downgrade() -> None:
    """Intentionally empty: see the note above on why the old value is not restored."""
