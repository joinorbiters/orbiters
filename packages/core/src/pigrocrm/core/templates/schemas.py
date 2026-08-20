"""API/service shapes for `Template` (models.py), detached from the ORM row.

No brief exists for this task (task-8-brief.md was never written to
`.superpowers/sdd/2026-08-10-slice-2-documenti-e-template/`); these shapes are
derived directly from `Template`'s own committed columns (nome String(120), tipo
String(20), corpo_markdown Text, variabili_dichiarate JSONB, attivo Boolean) and from
the conventions every sibling domain in this package already follows (`customers/
schemas.py`, `fields/schemas.py`, `pipeline/schemas.py`).
"""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pigrocrm.core.documents.schemas import DocumentTipo
from pigrocrm.core.fields.types import OPTION_TYPES, FieldType
from pigrocrm.core.validation import SafeStr

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
    tipo: DocumentTipo = "offerta"
    # No `max_length`: the column is `Text`, unbounded. `SafeStr` still closes the
    # NUL-byte gap a plain `str` would leave open on a native Postgres column.
    corpo_markdown: SafeStr = ""
    variabili_dichiarate: list[TemplateVariable] = Field(default_factory=list)
    attivo: bool = True


class TemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: SafeStr | None = Field(default=None, max_length=NOME_MAX_LENGTH)
    tipo: DocumentTipo | None = None
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
    tipo: DocumentTipo | None = None
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
    """

    id: UUID
    nome: str
    tipo: str
    # The compilation-form variables -- what a human (or an agent on their behalf) is
    # expected to actually supply values for.
    variabili_dichiarate: list[TemplateVariable]
    # Every dotted path the template body references at the top level (parser.
    # declared_paths's `root`), rendered as "a.b" strings: a superset of
    # `variabili_dichiarate`'s own names, since it also includes context paths like
    # `cliente.ragione_sociale` or `emittente.partita_iva` that a caller must supply
    # even though no compilation-form field exists for them.
    percorsi_radice: list[str]
    # Paths referenced only inside an `#each` body (parser.declared_paths's
    # `loop_relative`): the shape each element of whichever root array the loop
    # iterates must have, never something a caller supplies at the root itself.
    percorsi_per_ciclo: list[str]


__all__ = [
    "NOME_MAX_LENGTH",
    "TemplateCreate",
    "TemplateDescription",
    "TemplateListQuery",
    "TemplatePage",
    "TemplateRead",
    "TemplateUpdate",
    "TemplateVariable",
]
