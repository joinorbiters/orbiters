"""invoices.importata_da: 'the previous system' becomes 'esterno'

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

The downgrade puts `'the previous system'` back rather than dropping to `NULL`: a database rolled back
to 0028 is read by code that knows only the old literal, and `NULL` there does not mean
"imported from somewhere I forgot" -- it means "pigroCRM issued this itself", which for
these rows is false and would put fourteen invoices back in the reach of
`export_invoice_xml` and of a PDF regeneration.

Scoped by value, not by year or id: any row carrying the old literal is a row this
rename is about, and `WHERE importata_da = 'the previous system'` leaves every `NULL` untouched.

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


def _rename(old: str, new: str) -> None:
    op.execute(f"UPDATE invoices SET importata_da = '{new}' WHERE importata_da = '{old}'")
    op.execute(
        f"""
        UPDATE activities
           SET payload = jsonb_set(payload, '{{importata_da}}', '"{new}"'::jsonb)
         WHERE kind = 'imported'
           AND payload->>'importata_da' = '{old}'
        """
    )


def upgrade() -> None:
    _rename("the previous system", "esterno")


def downgrade() -> None:
    _rename("esterno", "the previous system")
