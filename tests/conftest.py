"""
Fixtures compartidas para los tests de pytest.

Equivalente al setUp/TestCase de Django: cada test corre contra una base
SQLite en memoria nueva (fixture `db_engine`, function-scoped), así que no
hay estado compartido entre tests ni necesidad de limpiar manualmente.
"""
import os

# Core CRM
os.environ.setdefault("DATABASE_URL",  "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-only-for-pytest")
os.environ.setdefault("BOT_API_KEY",    "test-bot-api-key-pytest")

# Webhooks de pasarelas de pago (routers/webhooks.py, leídas al importar el módulo)
os.environ.setdefault("MP_WEBHOOK_SECRET",     "test-mp-webhook-secret")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "test-stripe-webhook-secret")

# Virtual Receptionist (required by pydantic-settings at import time)
os.environ.setdefault("GEMINI_API_KEY",          "test-gemini-key-pytest")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN",   "test-verify-token")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN",   "test-access-token")
os.environ.setdefault("CRM_DM_GLOBAL_API_URL",   "http://localhost:9999")
os.environ.setdefault("GOOGLE_SHEETS_ID",         "test-sheets-id")
os.environ.setdefault("PRECHECKIN_FORM_URL",      "https://test.crm.com/precheckin/")

from typing import Iterator, Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from auth import crear_token, hash_password
from database import get_db
from feedback_models import Organizacion, ServicioFeedbackConfig
from main import app
from models import Base, Usuario


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


@pytest.fixture()
def crear_usuario(db_session: Session):
    """Factory: crea un Usuario interno con contraseña hasheada.

    Uso: crear_usuario(username="ana", rol="admin", password="Clave1234") -> Usuario
    """

    def _crear(
        username: str = "usuario_test",
        email: Optional[str] = None,
        password: str = "ClaveSegura1",
        rol: str = "soporte",
        activo: bool = True,
    ) -> Usuario:
        usuario = Usuario(
            username=username,
            email=email or f"{username}@test.com",
            hashed_password=hash_password(password),
            rol=rol,
            activo=activo,
        )
        db_session.add(usuario)
        db_session.commit()
        db_session.refresh(usuario)
        return usuario

    return _crear


def auth_headers(usuario: Usuario) -> dict:
    """Genera cabeceras Authorization: Bearer <jwt> para un Usuario dado."""
    token = crear_token(username=usuario.username, rol=usuario.rol)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_headers(crear_usuario):
    """Cabeceras de autenticación listas para un usuario con rol 'admin'."""
    usuario = crear_usuario(username="admin_test", rol="admin")
    return auth_headers(usuario)


@pytest.fixture()
def soporte_headers(crear_usuario):
    """Cabeceras de autenticación listas para un usuario con rol 'soporte'."""
    usuario = crear_usuario(username="soporte_test", rol="soporte")
    return auth_headers(usuario)
