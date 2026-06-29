import os
from collections.abc import Generator

from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker


# SQLite requiere INTEGER (no BIGINT) para que PRIMARY KEY AUTOINCREMENT funcione.
# Este override solo actúa cuando el dialecto es sqlite.
@compiles(BigInteger, "sqlite")
def _bigint_sqlite(element, compiler, **kw):
    return "INTEGER"

DATABASE_URL = os.environ["DATABASE_URL"]  # ej: postgresql+psycopg2://user:pass@host/db

# SQLite en dev requiere check_same_thread=False para FastAPI
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
