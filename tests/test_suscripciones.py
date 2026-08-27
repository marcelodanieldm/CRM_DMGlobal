"""
Tests del router de Suscripciones (routers/suscripciones.py).

RBAC:
  Lectura                       → admin + soporte
  Alta (POST)                   → solo admin
  Cambio de estado (PUT /estado) → admin (cualquier estado) / soporte (no puede desactivar)
"""
from models import Cliente, Servicio

URL = "/api/v1/suscripciones/"


def _crear_cliente(db_session, cuit="20123456789"):
    cliente = Cliente(razon_social="Cliente Test", cuit_cuil=cuit)
    db_session.add(cliente)
    db_session.commit()
    db_session.refresh(cliente)
    return cliente


def _crear_servicio(db_session, nombre="Monitoreo Web", precio_base=10000.0, activo=True):
    servicio = Servicio(
        nombre=nombre,
        precio_base=precio_base,
        moneda="ARS",
        tipo_ejecucion="mensual",
        tipo_servicio="bot",
        activo=activo,
    )
    db_session.add(servicio)
    db_session.commit()
    db_session.refresh(servicio)
    return servicio


class TestListarSuscripciones:
    def test_admin_puede_listar_vacio(self, client, admin_headers):
        respuesta = client.get(URL, headers=admin_headers)

        assert respuesta.status_code == 200
        assert respuesta.json() == []

    def test_soporte_puede_listar(self, client, soporte_headers):
        respuesta = client.get(URL, headers=soporte_headers)

        assert respuesta.status_code == 200

    def test_sin_token_devuelve_401(self, client):
        assert client.get(URL).status_code == 401

    def test_filtro_por_cliente_id(self, client, admin_headers, db_session):
        cliente1 = _crear_cliente(db_session, cuit="20111111111")
        cliente2 = _crear_cliente(db_session, cuit="20222222222")
        servicio = _crear_servicio(db_session)

        client.post(
            URL,
            json={
                "cliente_id": cliente1.id,
                "servicio_id": servicio.id,
                "pasarela_pago": "manual",
            },
            headers=admin_headers,
        )
        client.post(
            URL,
            json={
                "cliente_id": cliente2.id,
                "servicio_id": servicio.id,
                "pasarela_pago": "manual",
            },
            headers=admin_headers,
        )

        respuesta = client.get(URL, params={"cliente_id": cliente1.id}, headers=admin_headers)

        data = respuesta.json()
        assert len(data) == 1
        assert data[0]["cliente_id"] == cliente1.id


class TestCrearSuscripcion:
    def test_admin_puede_crear_y_hereda_precio_del_servicio(
        self, client, admin_headers, db_session
    ):
        cliente = _crear_cliente(db_session)
        servicio = _crear_servicio(db_session, precio_base=15000.0)

        respuesta = client.post(
            URL,
            json={
                "cliente_id": cliente.id,
                "servicio_id": servicio.id,
                "pasarela_pago": "mercadopago",
            },
            headers=admin_headers,
        )

        assert respuesta.status_code == 201
        data = respuesta.json()
        assert data["precio_acordado"] == 15000.0
        assert data["moneda"] == "ARS"
        assert data["estado_suscripcion"] == "activa"
        assert data["servicio_nombre"] == servicio.nombre

    def test_soporte_no_puede_crear(self, client, soporte_headers, db_session):
        cliente = _crear_cliente(db_session)
        servicio = _crear_servicio(db_session)

        respuesta = client.post(
            URL,
            json={
                "cliente_id": cliente.id,
                "servicio_id": servicio.id,
                "pasarela_pago": "manual",
            },
            headers=soporte_headers,
        )

        assert respuesta.status_code == 403

    def test_servicio_inactivo_devuelve_404(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)
        servicio = _crear_servicio(db_session, activo=False)

        respuesta = client.post(
            URL,
            json={
                "cliente_id": cliente.id,
                "servicio_id": servicio.id,
                "pasarela_pago": "manual",
            },
            headers=admin_headers,
        )

        assert respuesta.status_code == 404

    def test_pasarela_invalida_devuelve_422(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)
        servicio = _crear_servicio(db_session)

        respuesta = client.post(
            URL,
            json={
                "cliente_id": cliente.id,
                "servicio_id": servicio.id,
                "pasarela_pago": "paypal",
            },
            headers=admin_headers,
        )

        assert respuesta.status_code == 422


class TestActualizarEstado:
    def _crear_suscripcion(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)
        servicio = _crear_servicio(db_session)
        return client.post(
            URL,
            json={
                "cliente_id": cliente.id,
                "servicio_id": servicio.id,
                "pasarela_pago": "manual",
            },
            headers=admin_headers,
        ).json()

    def test_admin_puede_desactivar(self, client, admin_headers, db_session):
        sub = self._crear_suscripcion(client, admin_headers, db_session)

        respuesta = client.put(
            f"{URL}{sub['id']}/estado",
            json={"estado": "desactivada"},
            headers=admin_headers,
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["estado_suscripcion"] == "desactivada"

    def test_soporte_puede_pausar(self, client, admin_headers, soporte_headers, db_session):
        sub = self._crear_suscripcion(client, admin_headers, db_session)

        respuesta = client.put(
            f"{URL}{sub['id']}/estado",
            json={"estado": "pausada"},
            headers=soporte_headers,
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["estado_suscripcion"] == "pausada"
        assert respuesta.json()["fecha_ultima_pausa"] is not None

    def test_soporte_no_puede_desactivar(self, client, admin_headers, soporte_headers, db_session):
        sub = self._crear_suscripcion(client, admin_headers, db_session)

        respuesta = client.put(
            f"{URL}{sub['id']}/estado",
            json={"estado": "desactivada"},
            headers=soporte_headers,
        )

        assert respuesta.status_code == 403

    def test_estado_invalido_devuelve_422(self, client, admin_headers, db_session):
        sub = self._crear_suscripcion(client, admin_headers, db_session)

        respuesta = client.put(
            f"{URL}{sub['id']}/estado",
            json={"estado": "cancelada"},
            headers=admin_headers,
        )

        assert respuesta.status_code == 422

    def test_suscripcion_inexistente_devuelve_404(self, client, admin_headers):
        respuesta = client.put(
            f"{URL}99999/estado", json={"estado": "activa"}, headers=admin_headers
        )

        assert respuesta.status_code == 404
