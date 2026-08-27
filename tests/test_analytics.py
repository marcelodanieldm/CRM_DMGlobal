"""
Tests del router de Analytics (routers/analytics.py). Todos los endpoints
requieren rol 'admin'.
"""
import csv
from io import StringIO

from models import Cliente, Servicio, Suscripcion

SALUD_URL = "/api/v1/analytics/servicios/salud"


def _crear_cliente(db_session, cuit="20123456789"):
    cliente = Cliente(razon_social="Cliente Analytics", cuit_cuil=cuit)
    db_session.add(cliente)
    db_session.commit()
    db_session.refresh(cliente)
    return cliente


def _crear_servicio(db_session, nombre="Monitoreo Web", precio_base=10000.0):
    servicio = Servicio(
        nombre=nombre,
        precio_base=precio_base,
        moneda="ARS",
        tipo_ejecucion="mensual",
        tipo_servicio="bot",
        activo=True,
    )
    db_session.add(servicio)
    db_session.commit()
    db_session.refresh(servicio)
    return servicio


def _crear_suscripcion(db_session, cliente, servicio, estado="activa", precio_acordado=None):
    sub = Suscripcion(
        cliente_id=cliente.id,
        servicio_id=servicio.id,
        precio_acordado=precio_acordado,
        moneda="ARS",
        estado_suscripcion=estado,
        pasarela_pago="manual",
    )
    db_session.add(sub)
    db_session.commit()
    db_session.refresh(sub)
    return sub


class TestAutenticacion:
    def test_sin_token_devuelve_401(self, client):
        assert client.get(SALUD_URL).status_code == 401

    def test_soporte_no_puede_acceder(self, client, soporte_headers):
        respuesta = client.get(SALUD_URL, headers=soporte_headers)

        assert respuesta.status_code == 403


class TestSaludServicios:
    def test_sin_servicios_devuelve_lista_vacia(self, client, admin_headers):
        respuesta = client.get(SALUD_URL, headers=admin_headers)

        assert respuesta.status_code == 200
        assert respuesta.json() == []

    def test_cuenta_solo_suscripciones_activas(self, client, admin_headers, db_session):
        cliente1 = _crear_cliente(db_session, cuit="20111111111")
        cliente2 = _crear_cliente(db_session, cuit="20222222222")
        servicio = _crear_servicio(db_session, precio_base=10000.0)
        _crear_suscripcion(db_session, cliente1, servicio, estado="activa")
        _crear_suscripcion(db_session, cliente2, servicio, estado="pausada")

        respuesta = client.get(SALUD_URL, headers=admin_headers)

        data = respuesta.json()
        assert len(data) == 1
        assert data[0]["clientes_activos"] == 1
        assert data[0]["mrr_generado"] == 10000.0

    def test_mrr_usa_precio_acordado_si_existe(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)
        servicio = _crear_servicio(db_session, precio_base=10000.0)
        _crear_suscripcion(
            db_session, cliente, servicio, estado="activa", precio_acordado=8000.0
        )

        respuesta = client.get(SALUD_URL, headers=admin_headers)

        assert respuesta.json()[0]["mrr_generado"] == 8000.0

    def test_servicio_inactivo_no_aparece(self, client, admin_headers, db_session):
        servicio = _crear_servicio(db_session)
        servicio.activo = False
        db_session.commit()

        respuesta = client.get(SALUD_URL, headers=admin_headers)

        assert respuesta.json() == []


class TestExportarCsv:
    def _url(self, servicio_id):
        return f"/api/v1/analytics/servicios/{servicio_id}/exportar"

    def test_servicio_inexistente_devuelve_404(self, client, admin_headers):
        respuesta = client.get(self._url(99999), headers=admin_headers)

        assert respuesta.status_code == 404

    def test_exporta_csv_con_encabezado_y_filas(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)
        servicio = _crear_servicio(db_session)
        _crear_suscripcion(db_session, cliente, servicio, estado="activa")

        respuesta = client.get(self._url(servicio.id), headers=admin_headers)

        assert respuesta.status_code == 200
        assert respuesta.headers["content-type"].startswith("text/csv")
        assert "attachment" in respuesta.headers["content-disposition"]

        filas = list(csv.reader(StringIO(respuesta.text)))
        assert filas[0] == [
            "Razón Social",
            "CUIT/CUIL",
            "Precio Acordado (ARS)",
            "Estado Suscripción",
            "Pasarela de Pago",
            "Fecha de Inicio",
        ]
        assert len(filas) == 2
        assert filas[1][0] == "Cliente Analytics"

    def test_sin_suscripciones_solo_devuelve_encabezado(self, client, admin_headers, db_session):
        servicio = _crear_servicio(db_session)

        respuesta = client.get(self._url(servicio.id), headers=admin_headers)

        filas = list(csv.reader(StringIO(respuesta.text)))
        assert len(filas) == 1
