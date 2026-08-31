"""API/service shapes for `Template` (models.py), detached from the ORM row.

No brief exists for this task (task-8-brief.md was never written to
`.superpowers/sdd/2026-08-10-slice-2-documenti-e-template/`); these shapes are
derived directly from `Template`'s own committed columns (nome String(120), tipo
String(20), corpo_markdown Text, variabili_dichiarate JSONB, attivo Boolean) and from
the conventions every sibling domain in this package already follows (`customers/
schemas.py`, `fields/schemas.py`, `pipeline/schemas.py`).
"""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pigrocrm.core.fields.types import OPTION_TYPES, FieldType
from pigrocrm.core.validation import SafeStr

# Templates cover more than documents: slice 5 adds an `email` body and a `sollecito`.
# `DocumentTipo` -- which this used to reuse -- is deliberately left alone rather than
# extended, because no `documents` row is ever an email, and appending these two there
# would make them legal document types on every document endpoint in the API. The
# document-only values (`fattura`, `fattura_xml`, `proforma`, `rapporto_ore`) are not
# mirrored back the other way either, with one exception: `rapporto_ore` is the tipo
# `TemplateService.seed_defaults` already stores on the shipped timesheet template, so
# dropping it here would make a shipped row unreadable through `TemplateRead`.
# `Template.tipo` is already `String(20)` with no constraint, so there is no migration.
TemplateTipo = Literal[
    "offerta",
    "contratto",
    "verbale",
    "documento",
    "rapporto_ore",
    "email",
    "sollecito",
]

# Mirrors `Template.nome`'s column width (models.py). Without this an over-length
# value reaches Postgres and raises sqlalchemy.exc.DataError -- not a subclass of
# IntegrityError, so the service's `except IntegrityError` around the unique-name
# constraint would not catch it.
NOME_MAX_LENGTH = 120

# `variabili_dichiarate` is a single JSONB column with no per-field width of its own,
# so nothing here is load-bearing against a schema-drift test the way NOME_MAX_LENGTH
# above is. Bounded anyway, mirroring `fields/schemas.py`'s KEY_MAX_LENGTH/
# LABEL_MAX_LENGTH exactly: an unbounded string nested inside a JSONB blob is still an
# unbounded string, and a compilation form has no more use for a 10 000-character
# variable name than a custom field definition does.
VARIABLE_NOME_MAX_LENGTH = 60
VARIABLE_ETICHETTA_MAX_LENGTH = 120


class TemplateVariable(BaseModel):
    """One entry of `variabili_dichiarate`: a variable the compilation form asks the
    user to fill in before rendering (spec 4.3) -- declared, not deduced. Shaped to
    match `templates.renderer.DeclaredVariable` field-for-field (`nome`, `etichetta`,
    `tipo`, `obbligatoria`), which is what `TemplateService.preview` builds from this
    on its way into `render_template`; `options` is the one addition, carrying a
    `select`/`multiselect` variable's own choices for the form to render, the same
    role `fields.types.FieldSpec.options` plays for a custom field definition -- the
    renderer itself has no use for it and `DeclaredVariable` does not carry it.
    """

    model_config = ConfigDict(extra="forbid")

    nome: SafeStr = Field(max_length=VARIABLE_NOME_MAX_LENGTH)
    etichetta: SafeStr = Field(max_length=VARIABLE_ETICHETTA_MAX_LENGTH)
    tipo: FieldType
    obbligatoria: bool = False
    options: list[SafeStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def _choice_types_require_options(self) -> Self:
        """Same rule, same reasoning as `fields.types.FieldSpec`'s own validator: a
        select/multiselect with no options can never accept a value."""
        if self.tipo in OPTION_TYPES and not self.options:
            raise ValueError(f"tipo {self.tipo!r} richiede almeno una opzione in 'options'")
        return self


class TemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: SafeStr = Field(max_length=NOME_MAX_LENGTH)
    tipo: TemplateTipo = "offerta"
    # No `max_length`: the column is `Text`, unbounded. `SafeStr` still closes the
    # NUL-byte gap a plain `str` would leave open on a native Postgres column.
    corpo_markdown: SafeStr = ""
    variabili_dichiarate: list[TemplateVariable] = Field(default_factory=list)
    attivo: bool = True


class TemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: SafeStr | None = Field(default=None, max_length=NOME_MAX_LENGTH)
    tipo: TemplateTipo | None = None
    corpo_markdown: SafeStr | None = None
    variabili_dichiarate: list[TemplateVariable] | None = None
    attivo: bool | None = None


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    tipo: str
    corpo_markdown: str
    variabili_dichiarate: list[TemplateVariable]
    attivo: bool
    created_at: datetime
    updated_at: datetime


class TemplateListQuery(BaseModel):
    search: str | None = None
    tipo: TemplateTipo | None = None
    # `Template` has no `deleted_at` (task 6's own decision -- see its model
    # docstring): `attivo` is its lifecycle flag instead, so this is the equivalent
    # of every other domain's default "hide the archived ones" list behaviour.
    include_inactive: bool = False
    limit: int = Field(default=50, ge=1, le=200)
    cursor: UUID | None = None


class TemplatePage(BaseModel):
    items: list[TemplateRead]
    next_cursor: UUID | None


class TemplateDescription(BaseModel):
    """What `TemplateService.describe` returns: everything an agent needs to know
    about a template *before* asking the user to fill anything in, so the MCP
    `describe_template` tool this is built for is actually worth calling first.

    Deliberately its own type, not a reuse of `Template`'s own column names:
    `variabili` here (not `variabili_dichiarate`, which stays the model's actual
    column name) because this object's audience is different -- the frontend's
    template dialog calls `variablesToFields(description.variabili)` directly.
    """

    id: UUID
    nome: str
    tipo: str
    # The compilation-form variables -- what a human (or an agent on their behalf) is
    # expected to actually supply values for.
    variabili: list[TemplateVariable]
    # Every path the template body reads at the top level only (parser.
    # declared_paths's `root`), each as a list of segments: describe answers "what
    # must the caller supply", and a caller supplies root-level values, never a
    # loop-relative one -- `{{nome}}` inside an `#each righe` body describes the
    # shape of each element of `righe`, not something provided directly. That split
    # belongs to `declared_paths` and stays there; this field never mixes the two
    # back together. A superset of `variabili`'s own names, since it also includes
    # context paths like `cliente.ragione_sociale` or `emittente.partita_iva` that a
    # caller must supply even though no compilation-form field exists for them.
    percorsi_usati: list[list[str]]
    # Declared (in `variabili`) but never referenced by any root-level path: a
    # compilation-form field nobody's document will ever show. An authoring mistake
    # worth surfacing here, not just a naming footnote.
    variabili_non_usate: list[str]


__all__ = [
    "NOME_MAX_LENGTH",
    "TemplateTipo",
    "TemplateCreate",
    "TemplateDescription",
    "TemplateListQuery",
    "TemplatePage",
    "TemplateRead",
    "TemplateUpdate",
    "TemplateVariable",
]
