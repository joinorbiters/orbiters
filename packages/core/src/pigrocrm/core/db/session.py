from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from pigrocrm.core.config import Settings


def create_engine_from_settings(settings: Settings) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
