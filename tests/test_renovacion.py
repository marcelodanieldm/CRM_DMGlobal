"""
Tests unitarios de tasks/renovacion.py — cron de expiración automática de
suscripciones vencidas.

`_pausar_vencidas_sync` usa `SessionLocal` importado directamente de
database.py (no la dependencia `get_db` que sobreescribe el fixture
`client`), así que se parchea `tasks.renovacion.SessionLocal` para que
apunte al mismo engine SQLite en memoria (`db_engine`) usado por el test.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from sqlalchemy.orm import sessionmaker

import tasks.renovacion as renovacion
from models import AuditLog, Cliente, Servicio, Suscripcion


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _crear_suscripcion(db_session, *, estado="activa", fecha_proxima_renovacion=None, cuit="20123456789"):
    cliente = Cliente(razon_social="Cliente Cron", cuit_cuil=cuit)
    servicio = Servicio(
        nombre="Monitoreo Web", precio_base=10000.0, moneda="ARS",
        tipo_ejecucion="mensual", tipo_servicio="bot", activo=True,
    )
    db_session.add_all([cliente, servicio])
    db_session.flush()

    sub = Suscripcion(
        cliente_id=cliente.id, servicio_id=servicio.id,
        estado_suscripcion=estado, pasarela_pago="manual",
        fecha_proxima_renovacion=fecha_proxima_renovacion,
    )
    db_session.add(sub)
    db_session.commit()
    db_session.refresh(sub)
    return sub


class TestPausarVencidasSync:
    def test_sin_suscripciones_vencidas_devuelve_lista_vacia(self, db_engine, monkeypatch):
        TestingSessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
        monkeypatch.setattr(renovacion, "SessionLocal", TestingSessionLocal)

        resultado = renovacion._pausar_vencidas_sync()

        assert resultado == []

    def test_pausa_suscripciones_vencidas_y_registra_audit_log(self, db_engine, monkeypatch):
        TestingSessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
        monkeypatch.setattr(renovacion, "SessionLocal", TestingSessionLocal)

        session = TestingSessionLocal()
        vencida = _crear_suscripcion(
            session, estado="activa",
            fecha_proxima_renovacion=datetime.now(timezone.utc) - timedelta(days=1),
        )
        sub_id = vencida.id
        session.close()

        resultado = renovacion._pausar_vencidas_sync()

        assert len(resultado) == 1
        assert resultado[0]["suscripcion_id"] == sub_id
        assert resultado[0]["cuit"] == "20123456789"
        assert resultado[0]["nombre_servicio"] == "Monitoreo Web"

        verificacion = TestingSessionLocal()
        sub_actualizada = verificacion.get(Suscripcion, sub_id)
        assert sub_actualizada.estado_suscripcion == "pausada"
        assert sub_actualizada.fecha_ultima_pausa is not None

        audit = verificacion.query(AuditLog).filter_by(suscripcion_id=sub_id).first()
        assert audit is not None
        assert audit.accion == "expiracion_automatica"
        assert audit.usuario_interno == "sistema:cron"
        verificacion.close()

    def test_no_toca_suscripciones_activas_sin_vencer(self, db_engine, monkeypatch):
        TestingSessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
        monkeypatch.setattr(renovacion, "SessionLocal", TestingSessionLocal)

        session = TestingSessionLocal()
        _crear_suscripcion(
            session, estado="activa",
            fecha_proxima_renovacion=datetime.now(timezone.utc) + timedelta(days=5),
        )
        session.close()

        resultado = renovacion._pausar_vencidas_sync()

        assert resultado == []

    def test_no_toca_suscripciones_ya_pausadas_aunque_esten_vencidas(self, db_engine, monkeypatch):
        TestingSessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
        monkeypatch.setattr(renovacion, "SessionLocal", TestingSessionLocal)

        session = TestingSessionLocal()
        _crear_suscripcion(
            session, estado="pausada",
            fecha_proxima_renovacion=datetime.now(timezone.utc) - timedelta(days=1),
        )
        session.close()

        resultado = renovacion._pausar_vencidas_sync()

        assert resultado == []


class TestVerificarRenovacionesVencidas:
    def test_notifica_por_cada_suscripcion_pausada(self, db_engine, monkeypatch):
        TestingSessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
        monkeypatch.setattr(renovacion, "SessionLocal", TestingSessionLocal)

        session = TestingSessionLocal()
        vencida = _crear_suscripcion(
            session, estado="activa",
            fecha_proxima_renovacion=datetime.now(timezone.utc) - timedelta(days=1),
        )
        sub_id = vencida.id
        session.close()

        mock_notificar = AsyncMock()
        monkeypatch.setattr(renovacion, "notificar_cambio_estado", mock_notificar)

        run(renovacion.verificar_renovaciones_vencidas())

        mock_notificar.assert_awaited_once_with(
            cuit="20123456789",
            nombre_servicio="Monitoreo Web",
            nuevo_estado="pausada",
            pasarela="sistema:cron",
            suscripcion_id=sub_id,
        )

    def test_sin_vencidas_no_notifica(self, db_engine, monkeypatch):
        TestingSessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
        monkeypatch.setattr(renovacion, "SessionLocal", TestingSessionLocal)

        mock_notificar = AsyncMock()
        monkeypatch.setattr(renovacion, "notificar_cambio_estado", mock_notificar)

        run(renovacion.verificar_renovaciones_vencidas())

        mock_notificar.assert_not_awaited()
