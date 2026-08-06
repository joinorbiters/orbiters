from collections.abc import Iterator
from contextlib import contextmanager

from pigrocrm.core.config import Settings
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_engine_from_settings(settings: Settings) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
