"""
Tests del endpoint de validación de acceso para bots (routers/validacion.py).

GET /api/v1/validar-acceso — requiere cabecera X-API-Key.
"""
import routers.validacion as validacion_router
from models import Cliente, Servicio, Suscripcion

URL = "/api/v1/validar-acceso"
API_KEY = validacion_router._BOT_API_KEY


def _crear_cliente(db_session, cuit="20123456789"):
    cliente = Cliente(razon_social="Cliente Bot", cuit_cuil=cuit)
    db_session.add(cliente)
    db_session.commit()
    db_session.refresh(cliente)
    return cliente


def _crear_servicio(db_session, nombre="Monitoreo Web", activo=True):
    servicio = Servicio(
        nombre=nombre,
        precio_base=10000.0,
        moneda="ARS",
        tipo_ejecucion="mensual",
        tipo_servicio="bot",
        activo=activo,
    )
    db_session.add(servicio)
    db_session.commit()
    db_session.refresh(servicio)
    return servicio


def _crear_suscripcion(db_session, cliente, servicio, estado="activa"):
    sub = Suscripcion(
        cliente_id=cliente.id,
        servicio_id=servicio.id,
        estado_suscripcion=estado,
        pasarela_pago="manual",
    )
    db_session.add(sub)
    db_session.commit()
    db_session.refresh(sub)
    return sub


class TestAutenticacionApiKey:
    def test_sin_api_key_devuelve_401(self, client):
        respuesta = client.get(
            URL, params={"cuit": "20123456789", "nombre_servicio": "Monitoreo Web"}
        )

        assert respuesta.status_code == 401

    def test_api_key_incorrecta_devuelve_401(self, client):
        respuesta = client.get(
            URL,
            params={"cuit": "20123456789", "nombre_servicio": "Monitoreo Web"},
            headers={"X-API-Key": "clave-incorrecta"},
        )

        assert respuesta.status_code == 401


class TestValidarAcceso:
    def test_suscripcion_activa_devuelve_autorizado(self, client, db_session):
        cliente = _crear_cliente(db_session)
        servicio = _crear_servicio(db_session)
        _crear_suscripcion(db_session, cliente, servicio, estado="activa")

        respuesta = client.get(
            URL,
            params={"cuit": cliente.cuit_cuil, "nombre_servicio": servicio.nombre},
            headers={"X-API-Key": API_KEY},
        )

        assert respuesta.status_code == 200
        assert respuesta.json() == {"autorizado": True, "estado": "activa"}

    def test_suscripcion_pausada_devuelve_no_autorizado_con_estado_real(
        self, client, db_session
    ):
        cliente = _crear_cliente(db_session)
        servicio = _crear_servicio(db_session)
        _crear_suscripcion(db_session, cliente, servicio, estado="pausada")

        respuesta = client.get(
            URL,
            params={"cuit": cliente.cuit_cuil, "nombre_servicio": servicio.nombre},
            headers={"X-API-Key": API_KEY},
        )

        assert respuesta.status_code == 200
        assert respuesta.json() == {"autorizado": False, "estado": "pausada"}

    def test_sin_suscripcion_devuelve_no_encontrada(self, client, db_session):
        cliente = _crear_cliente(db_session)
        _crear_servicio(db_session)

        respuesta = client.get(
            URL,
            params={"cuit": cliente.cuit_cuil, "nombre_servicio": "Monitoreo Web"},
            headers={"X-API-Key": API_KEY},
        )

        assert respuesta.status_code == 200
        assert respuesta.json() == {"autorizado": False, "estado": "no_encontrada"}

    def test_servicio_inactivo_no_autoriza_aunque_este_activa(self, client, db_session):
        cliente = _crear_cliente(db_session)
        servicio = _crear_servicio(db_session, activo=False)
        _crear_suscripcion(db_session, cliente, servicio, estado="activa")

        respuesta = client.get(
            URL,
            params={"cuit": cliente.cuit_cuil, "nombre_servicio": servicio.nombre},
            headers={"X-API-Key": API_KEY},
        )

        assert respuesta.json()["autorizado"] is False
