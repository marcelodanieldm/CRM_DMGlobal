"""
Tests del router de Servicios (routers/servicios.py).

RBAC:
  Lectura            → admin + soporte
  Escritura (CUD)    → solo admin
"""
URL = "/api/v1/servicios/"


def _payload(**overrides):
    base = {
        "nombre": "Monitoreo Web",
        "descripcion": "Scraping periódico de precios",
        "precio_base": 15000.0,
        "moneda": "ARS",
        "tipo_ejecucion": "mensual",
        "tipo_servicio": "bot",
        "activo": True,
    }
    base.update(overrides)
    return base


class TestAutenticacion:
    def test_sin_token_devuelve_401(self, client):
        assert client.get(URL).status_code == 401

    def test_token_invalido_devuelve_401(self, client):
        respuesta = client.get(URL, headers={"Authorization": "Bearer token-basura"})

        assert respuesta.status_code == 401


class TestListarYObtener:
    def test_soporte_puede_listar(self, client, soporte_headers):
        respuesta = client.get(URL, headers=soporte_headers)

        assert respuesta.status_code == 200
        assert respuesta.json() == []

    def test_admin_puede_listar(self, client, admin_headers):
        respuesta = client.get(URL, headers=admin_headers)

        assert respuesta.status_code == 200

    def test_lista_por_defecto_excluye_inactivos(self, client, admin_headers):
        activo = client.post(URL, json=_payload(), headers=admin_headers).json()
        inactivo = client.post(
            URL, json=_payload(nombre="Servicio B"), headers=admin_headers
        ).json()
        client.delete(f"{URL}{inactivo['id']}", headers=admin_headers)

        respuesta = client.get(URL, headers=admin_headers)

        ids = [s["id"] for s in respuesta.json()]
        assert ids == [activo["id"]]

    def test_lista_con_solo_activos_false_incluye_todos(self, client, admin_headers):
        client.post(URL, json=_payload(), headers=admin_headers)
        inactivo = client.post(
            URL, json=_payload(nombre="Servicio B"), headers=admin_headers
        ).json()
        client.delete(f"{URL}{inactivo['id']}", headers=admin_headers)

        respuesta = client.get(URL, params={"solo_activos": False}, headers=admin_headers)

        assert len(respuesta.json()) == 2

    def test_obtener_servicio_inexistente_devuelve_404(self, client, admin_headers):
        respuesta = client.get(f"{URL}99999", headers=admin_headers)

        assert respuesta.status_code == 404


class TestCrearServicio:
    def test_admin_puede_crear(self, client, admin_headers):
        respuesta = client.post(URL, json=_payload(), headers=admin_headers)

        assert respuesta.status_code == 201
        assert respuesta.json()["nombre"] == "Monitoreo Web"

    def test_soporte_no_puede_crear(self, client, soporte_headers):
        respuesta = client.post(URL, json=_payload(), headers=soporte_headers)

        assert respuesta.status_code == 403

    def test_nombre_duplicado_devuelve_409(self, client, admin_headers):
        client.post(URL, json=_payload(), headers=admin_headers)

        respuesta = client.post(URL, json=_payload(), headers=admin_headers)

        assert respuesta.status_code == 409

    def test_precio_base_negativo_devuelve_422(self, client, admin_headers):
        respuesta = client.post(
            URL, json=_payload(precio_base=-10), headers=admin_headers
        )

        assert respuesta.status_code == 422


class TestActualizarServicio:
    def test_admin_puede_actualizar(self, client, admin_headers):
        creado = client.post(URL, json=_payload(), headers=admin_headers).json()

        respuesta = client.put(
            f"{URL}{creado['id']}",
            json=_payload(precio_base=20000.0),
            headers=admin_headers,
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["precio_base"] == 20000.0

    def test_soporte_no_puede_actualizar(self, client, admin_headers, soporte_headers):
        creado = client.post(URL, json=_payload(), headers=admin_headers).json()

        respuesta = client.put(
            f"{URL}{creado['id']}", json=_payload(), headers=soporte_headers
        )

        assert respuesta.status_code == 403

    def test_actualizar_a_nombre_de_otro_servicio_devuelve_409(self, client, admin_headers):
        client.post(URL, json=_payload(nombre="Servicio A"), headers=admin_headers)
        otro = client.post(
            URL, json=_payload(nombre="Servicio B"), headers=admin_headers
        ).json()

        respuesta = client.put(
            f"{URL}{otro['id']}",
            json=_payload(nombre="Servicio A"),
            headers=admin_headers,
        )

        assert respuesta.status_code == 409

    def test_actualizar_servicio_inexistente_devuelve_404(self, client, admin_headers):
        respuesta = client.put(f"{URL}99999", json=_payload(), headers=admin_headers)

        assert respuesta.status_code == 404


class TestEliminarServicio:
    def test_admin_puede_desactivar(self, client, admin_headers):
        creado = client.post(URL, json=_payload(), headers=admin_headers).json()

        respuesta = client.delete(f"{URL}{creado['id']}", headers=admin_headers)

        assert respuesta.status_code == 200
        assert respuesta.json()["activo"] is False

    def test_soporte_no_puede_eliminar(self, client, admin_headers, soporte_headers):
        creado = client.post(URL, json=_payload(), headers=admin_headers).json()

        respuesta = client.delete(f"{URL}{creado['id']}", headers=soporte_headers)

        assert respuesta.status_code == 403

    def test_eliminar_servicio_ya_desactivado_devuelve_409(self, client, admin_headers):
        creado = client.post(URL, json=_payload(), headers=admin_headers).json()
        client.delete(f"{URL}{creado['id']}", headers=admin_headers)

        respuesta = client.delete(f"{URL}{creado['id']}", headers=admin_headers)

        assert respuesta.status_code == 409

    def test_eliminar_servicio_inexistente_devuelve_404(self, client, admin_headers):
        respuesta = client.delete(f"{URL}99999", headers=admin_headers)

        assert respuesta.status_code == 404
