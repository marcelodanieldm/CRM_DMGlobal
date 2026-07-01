"""
Fixtures compartidas para los tests de pytest.

Equivalente al setUp/TestCase de Django: cada test corre contra una base
SQLite en memoria nueva (fixture `db_engine`, function-scoped), así que no
hay estado compartido entre tests ni necesidad de limpiar manualmente.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-only-for-pytest")

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database import get_db
from feedback_models import Organizacion, ServicioFeedbackConfig
from main import app
from models import Base


@pytest.fixture()
def db_engine():
    """Engine SQLite en memoria, con un único connection pool compartido
    (StaticPool) para que la API y el test vean la misma base de datos."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session(db_engine) -> Iterator[Session]:
    TestingSessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_engine) -> Iterator[TestClient]:
    """TestClient con get_db() sobreescrito para apuntar a db_engine."""
    TestingSessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)

    def _override_get_db() -> Iterator[Session]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def crear_config(db_session: Session):
    """Factory: crea una Organizacion + ServicioFeedbackConfig listas para usar.

    Uso: crear_config(estado_suscripcion="ACTIVO") -> ServicioFeedbackConfig
    """

    def _crear(
        estado_suscripcion: str = "ACTIVO",
        tipo_negocio: str = "HOTEL",
        nombre_organizacion: str = "Hotel Test",
    ) -> ServicioFeedbackConfig:
        organizacion = Organizacion(nombre=nombre_organizacion)
        db_session.add(organizacion)
        db_session.flush()

        config = ServicioFeedbackConfig(
            organizacion_id=organizacion.id,
            estado_suscripcion=estado_suscripcion,
            tipo_negocio=tipo_negocio,
            google_review_link="https://g.page/r/hotel-test/review",
        )
        db_session.add(config)
        db_session.commit()
        db_session.refresh(config)
        return config

    return _crear
