"""The whole configuration surface of this slice's automations: two booleans.

A single row, like `emitter_profile` (slice 2) and `fiscal_profile` (slice 3), and read
through `AutomationConfigRepository.get_or_create()` which creates it on first use. No
`singleton` CHECK constraint: the repository is the only writer and it never inserts a
second row, and a constraint pinning a magic primary key would be a second mechanism for
the same invariant.

No flow builder, no configurable conditions, no second effect per rule (spec §15). A flow
builder brings a condition evaluator, an execution order, a failure semantics and a way to
stop a loop: four mechanisms for a product that has two rules.
"""

from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class AutomationConfig(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "automation_config"

    # A1 -- offerta accettata -> deal vinto. Default on: an automation nobody switched on
    # is an automation nobody knows exists.
    a1_offerta_accettata_vince_deal: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default="true"
    )
    # A2 -- offerta inviata -> il deal avanza allo stage `code='offerta'`, only if its
    # current `posizione` is lower. Never backwards: see `AutomationRunner`.
    a2_offerta_inviata_avanza_deal: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default="true"
    )
