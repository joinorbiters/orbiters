from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from pigrocrm.core.actor import Actor
from pigrocrm.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from pigrocrm.core.templates.repository import TemplateRepository
from pigrocrm.core.templates.schemas import (
    TemplateCreate,
    TemplateListQuery,
    TemplateUpdate,
    TemplateVariable,
)
from pigrocrm.core.templates.service import TemplateService

ADMIN = Actor(id=None, type="system", role="admin")
READONLY = Actor(id=None, type="user", role="readonly")


def _create(**overrides: object) -> TemplateCreate:
    payload: dict[str, object] = {
        "nome": "Offerta Standard",
        "tipo": "offerta",
        "corpo_markdown": "Gentile {{cliente.ragione_sociale}}, offerta di {{importo}}.",
        "variabili_dichiarate": [
            {"nome": "importo", "etichetta": "Importo", "tipo": "currency", "obbligatoria": True}
        ],
    }
    payload.update(overrides)
    return TemplateCreate(**payload)  # type: ignore[arg-type]


def test_create_persists_a_template(db_session: Session) -> None:
    template = TemplateService(db_session).create(_create(), ADMIN)
    assert template.nome == "Offerta Standard"
    assert template.attivo is True
    assert template.variabili_dichiarate[0].nome == "importo"


def test_create_rejects_a_syntactically_invalid_body(db_session: Session) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        TemplateService(db_session).create(_create(corpo_markdown="{{#if x}}senza chiusura"), ADMIN)
    assert excinfo.value.details["entity"] == "template"


def test_create_rejects_a_duplicate_nome(db_session: Session) -> None:
    service = TemplateService(db_session)
    service.create(_create(), ADMIN)
    with pytest.raises(Conflict):
        service.create(_create(), ADMIN)


def test_create_rejects_a_case_only_duplicate_nome(db_session: Session) -> None:
    service = TemplateService(db_session)
    service.create(_create(), ADMIN)
    with pytest.raises(Conflict):
        service.create(_create(nome="OFFERTA STANDARD"), ADMIN)


def test_create_converts_a_true_insert_race_into_a_clean_conflict(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mirrors test_emitter.py's identical race test: forces the pre-check
    (`get_by_nome`) to report "no such template" for two successive creates, so only
    the database's own `uq_templates_nome` functional unique index stops the second
    -- proving the whole mutation, not just the pre-check, converts a real
    constraint violation into a clean `Conflict`."""
    service = TemplateService(db_session)
    monkeypatch.setattr(TemplateRepository, "get_by_nome", lambda self, nome: None)
    service.create(_create(), ADMIN)
    with pytest.raises(Conflict):
        service.create(_create(), ADMIN)

    monkeypatch.undo()
    page = TemplateService(db_session).list(_list_query(), ADMIN)
    assert len(page.items) == 1


def test_create_requires_admin(db_session: Session) -> None:
    with pytest.raises(PermissionDenied):
        TemplateService(db_session).create(_create(), READONLY)


def test_get_missing_template_raises_not_found(db_session: Session) -> None:
    with pytest.raises(NotFound):
        TemplateService(db_session).get(uuid4(), ADMIN)


def test_update_renames_a_template(db_session: Session) -> None:
    service = TemplateService(db_session)
    created = service.create(_create(), ADMIN)
    updated = service.update(created.id, TemplateUpdate(nome="Offerta Rivista"), ADMIN)
    assert updated.nome == "Offerta Rivista"
    assert updated.corpo_markdown == created.corpo_markdown


def test_update_to_a_case_only_variant_of_its_own_name_is_not_a_conflict(
    db_session: Session,
) -> None:
    service = TemplateService(db_session)
    created = service.create(_create(), ADMIN)
    updated = service.update(created.id, TemplateUpdate(nome="OFFERTA STANDARD"), ADMIN)
    assert updated.nome == "OFFERTA STANDARD"


def test_update_to_another_templates_name_is_a_conflict(db_session: Session) -> None:
    service = TemplateService(db_session)
    service.create(_create(), ADMIN)
    other = service.create(_create(nome="Contratto Base"), ADMIN)
    with pytest.raises(Conflict):
        service.update(other.id, TemplateUpdate(nome="Offerta Standard"), ADMIN)


def test_update_rejects_a_syntactically_invalid_body(db_session: Session) -> None:
    service = TemplateService(db_session)
    created = service.create(_create(), ADMIN)
    with pytest.raises(ValidationFailed):
        service.update(
            created.id, TemplateUpdate(corpo_markdown="{{#each x}}senza chiusura"), ADMIN
        )


def test_update_missing_template_raises_not_found(db_session: Session) -> None:
    with pytest.raises(NotFound):
        TemplateService(db_session).update(uuid4(), TemplateUpdate(nome="X"), ADMIN)


def test_update_requires_admin(db_session: Session) -> None:
    service = TemplateService(db_session)
    created = service.create(_create(), ADMIN)
    with pytest.raises(PermissionDenied):
        service.update(created.id, TemplateUpdate(nome="X"), READONLY)


def test_deactivate_then_activate_round_trips(db_session: Session) -> None:
    service = TemplateService(db_session)
    created = service.create(_create(), ADMIN)
    deactivated = service.deactivate(created.id, ADMIN)
    assert deactivated.attivo is False
    activated = service.activate(created.id, ADMIN)
    assert activated.attivo is True


def test_deactivate_requires_admin(db_session: Session) -> None:
    service = TemplateService(db_session)
    created = service.create(_create(), ADMIN)
    with pytest.raises(PermissionDenied):
        service.deactivate(created.id, READONLY)


def _list_query(**overrides: object) -> TemplateListQuery:
    return TemplateListQuery(**overrides)  # type: ignore[arg-type]


def test_list_hides_inactive_templates_by_default(db_session: Session) -> None:
    service = TemplateService(db_session)
    active = service.create(_create(), ADMIN)
    inactive = service.create(_create(nome="Contratto Base"), ADMIN)
    service.deactivate(inactive.id, ADMIN)

    page = service.list(_list_query(), ADMIN)
    assert [item.id for item in page.items] == [active.id]

    page_all = service.list(_list_query(include_inactive=True), ADMIN)
    assert {item.id for item in page_all.items} == {active.id, inactive.id}


def test_list_search_matches_nome_case_insensitively(db_session: Session) -> None:
    service = TemplateService(db_session)
    service.create(_create(), ADMIN)
    service.create(_create(nome="Contratto Base"), ADMIN)

    page = service.list(_list_query(search="offerta"), ADMIN)
    assert [item.nome for item in page.items] == ["Offerta Standard"]


def test_describe_reports_the_compilation_form_and_every_path_the_body_needs(
    db_session: Session,
) -> None:
    body = (
        "{{#if sconto}}Sconto applicato{{/if}}\n"
        "{{#each righe}}- {{nome}}: {{prezzo}}\n{{/each}}\n"
        "Cliente: {{cliente.nome}}"
    )
    service = TemplateService(db_session)
    created = service.create(
        _create(
            corpo_markdown=body,
            variabili_dichiarate=[
                {"nome": "sconto", "etichetta": "Sconto", "tipo": "checkbox", "obbligatoria": False}
            ],
        ),
        ADMIN,
    )

    description = service.describe(created.id, ADMIN)

    assert description.variabili_dichiarate[0].nome == "sconto"
    assert description.percorsi_radice == ["sconto", "righe", "cliente.nome"]
    assert description.percorsi_per_ciclo == ["nome", "prezzo"]


def test_describe_missing_template_raises_not_found(db_session: Session) -> None:
    with pytest.raises(NotFound):
        TemplateService(db_session).describe(uuid4(), ADMIN)


def test_preview_renders_compiled_markdown(db_session: Session) -> None:
    # No ASCII punctuation in either value: escaping.py's markdown escaper
    # deliberately escapes the entire punctuation class unconditionally (see its own
    # module docstring), so a value containing "." or "," would round-trip through
    # this assertion as "\." / "\," -- a fact about escaping, not about preview,
    # that a plain rendering test has no business depending on.
    service = TemplateService(db_session)
    created = service.create(_create(), ADMIN)

    preview = service.preview(
        created.id,
        {"cliente": {"ragione_sociale": "ACME Srl"}, "importo": "1500"},
        ADMIN,
    )

    assert preview.markdown == "Gentile ACME Srl, offerta di 1500."


def test_preview_fails_precisely_when_a_required_declared_variable_is_missing(
    db_session: Session,
) -> None:
    service = TemplateService(db_session)
    created = service.create(_create(), ADMIN)

    with pytest.raises(ValidationFailed) as excinfo:
        service.preview(created.id, {"cliente": {"ragione_sociale": "ACME Srl"}}, ADMIN)

    assert excinfo.value.details["field"] == "importo"


def test_preview_fails_precisely_on_an_unresolved_path(db_session: Session) -> None:
    service = TemplateService(db_session)
    created = service.create(_create(), ADMIN)

    with pytest.raises(ValidationFailed) as excinfo:
        service.preview(created.id, {"importo": "1.500,00"}, ADMIN)

    assert excinfo.value.details["field"] == "cliente.ragione_sociale"


def test_preview_missing_template_raises_not_found(db_session: Session) -> None:
    with pytest.raises(NotFound):
        TemplateService(db_session).preview(uuid4(), {}, ADMIN)


def test_a_select_variable_without_options_is_rejected() -> None:
    with pytest.raises(ValueError):
        TemplateVariable(nome="colore", etichetta="Colore", tipo="select", obbligatoria=False)
