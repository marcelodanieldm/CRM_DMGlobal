"""
Tests del router de Servicios Premium (routers/servicios_premium.py).

Endpoints por cliente:
  GET/PUT/DELETE  /api/v1/clientes/{id}/feedback-config
  GET/PUT/DELETE  /api/v1/clientes/{id}/recepcionista-config
  GET             /api/v1/clientes/{id}/servicios-premium

RBAC: lectura admin+soporte, escritura solo admin.
"""
from models import Cliente


def _crear_cliente(db_session, cuit="20123456789"):
    cliente = Cliente(razon_social="Cliente Premium", cuit_cuil=cuit)
    db_session.add(cliente)
    db_session.commit()
    db_session.refresh(cliente)
    return cliente


class TestServiciosPremiumCombinado:
    def test_cliente_sin_configs_devuelve_ambos_en_null(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)

        respuesta = client.get(
            f"/api/v1/clientes/{cliente.id}/servicios-premium", headers=admin_headers
        )

        assert respuesta.status_code == 200
        data = respuesta.json()
        assert data["feedback"] is None
        assert data["recepcionista"] is None

    def test_cliente_inexistente_devuelve_404(self, client, admin_headers):
        respuesta = client.get(
            "/api/v1/clientes/99999/servicios-premium", headers=admin_headers
        )

        assert respuesta.status_code == 404

    def test_soporte_puede_leer(self, client, soporte_headers, db_session):
        cliente = _crear_cliente(db_session)

        respuesta = client.get(
            f"/api/v1/clientes/{cliente.id}/servicios-premium", headers=soporte_headers
        )

        assert respuesta.status_code == 200


class TestFeedbackConfig:
    def _url(self, cliente_id):
        return f"/api/v1/clientes/{cliente_id}/feedback-config"

    def test_upsert_crea_la_configuracion(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)

        respuesta = client.put(
            self._url(cliente.id),
            json={"tipo_negocio": "HOTEL", "google_review_link": "https://g.page/x"},
            headers=admin_headers,
        )

        assert respuesta.status_code == 200
        data = respuesta.json()
        assert data["tipo_negocio"] == "HOTEL"
        assert data["cliente_id"] == cliente.id

    def test_upsert_actualiza_configuracion_existente(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)
        client.put(
            self._url(cliente.id), json={"tipo_negocio": "HOTEL"}, headers=admin_headers
        )

        respuesta = client.put(
            self._url(cliente.id), json={"tipo_negocio": "TOUR"}, headers=admin_headers
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["tipo_negocio"] == "TOUR"

    def test_soporte_no_puede_escribir(self, client, soporte_headers, db_session):
        cliente = _crear_cliente(db_session)

        respuesta = client.put(
            self._url(cliente.id), json={"tipo_negocio": "HOTEL"}, headers=soporte_headers
        )

        assert respuesta.status_code == 403

    def test_tipo_negocio_invalido_devuelve_422(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)

        respuesta = client.put(
            self._url(cliente.id), json={"tipo_negocio": "INVALIDO"}, headers=admin_headers
        )

        assert respuesta.status_code == 422

    def test_get_sin_configuracion_devuelve_404(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)

        respuesta = client.get(self._url(cliente.id), headers=admin_headers)

        assert respuesta.status_code == 404

    def test_get_cliente_inexistente_devuelve_404(self, client, admin_headers):
        respuesta = client.get(self._url(99999), headers=admin_headers)

        assert respuesta.status_code == 404

    def test_delete_elimina_la_configuracion(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)
        client.put(
            self._url(cliente.id), json={"tipo_negocio": "HOTEL"}, headers=admin_headers
        )

        respuesta = client.delete(self._url(cliente.id), headers=admin_headers)

        assert respuesta.status_code == 204
        assert client.get(self._url(cliente.id), headers=admin_headers).status_code == 404

    def test_delete_sin_configuracion_no_falla(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)

        respuesta = client.delete(self._url(cliente.id), headers=admin_headers)

        assert respuesta.status_code == 204


class TestRecepcionistaConfig:
    def _url(self, cliente_id):
        return f"/api/v1/clientes/{cliente_id}/recepcionista-config"

    def test_upsert_crea_la_configuracion(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)

        respuesta = client.put(
            self._url(cliente.id),
            json={"hotel_id": "HOTEL-01", "whatsapp_phone_number_id": "1234567890"},
            headers=admin_headers,
        )

        assert respuesta.status_code == 200
        data = respuesta.json()
        assert data["hotel_id"] == "HOTEL-01"
        assert data["cliente_id"] == cliente.id

    def test_soporte_no_puede_escribir(self, client, soporte_headers, db_session):
        cliente = _crear_cliente(db_session)

        respuesta = client.put(
            self._url(cliente.id), json={"hotel_id": "HOTEL-01"}, headers=soporte_headers
        )

        assert respuesta.status_code == 403

    def test_get_sin_configuracion_devuelve_404(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)

        respuesta = client.get(self._url(cliente.id), headers=admin_headers)

        assert respuesta.status_code == 404

    def test_delete_elimina_la_configuracion(self, client, admin_headers, db_session):
        cliente = _crear_cliente(db_session)
        client.put(
            self._url(cliente.id), json={"hotel_id": "HOTEL-01"}, headers=admin_headers
        )

        respuesta = client.delete(self._url(cliente.id), headers=admin_headers)

        assert respuesta.status_code == 204
