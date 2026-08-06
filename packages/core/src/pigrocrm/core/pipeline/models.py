from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from pigrocrm.core.db import Base, PrimaryKeyMixin, TimestampMixin


class PipelineStage(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "pipeline_stages"

    nome: Mapped[str] = mapped_column(String(60), nullable=False)
    posizione: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    probabilita_default: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
