"""
Tests del router de Clientes (routers/clientes.py).

Endpoints: GET /, GET /{id}, POST /, PATCH /{id}, DELETE /{id}
No requiere autenticación (sin dependencia de auth en el router).
"""
URL = "/api/v1/clientes/"


def _payload(**overrides):
    base = {
        "razon_social": "ACME S.A.",
        "cuit_cuil": "20123456789",
        "email_contacto": "acme@test.com",
        "telefono": "+54 11 4444-5555",
        "estado_general": "activo",
    }
    base.update(overrides)
    return base


class TestCrearCliente:
    def test_crear_cliente_devuelve_201_y_los_datos(self, client):
        respuesta = client.post(URL, json=_payload())

        assert respuesta.status_code == 201
        data = respuesta.json()
        assert data["razon_social"] == "ACME S.A."
        assert data["cuit_cuil"] == "20123456789"
        assert "id" in data

    def test_cuit_duplicado_devuelve_409(self, client):
        client.post(URL, json=_payload())

        respuesta = client.post(URL, json=_payload(razon_social="Otra Razón"))

        assert respuesta.status_code == 409

    def test_cuit_con_formato_invalido_devuelve_422(self, client):
        respuesta = client.post(URL, json=_payload(cuit_cuil="no-es-un-cuit"))

        assert respuesta.status_code == 422

    def test_razon_social_vacia_devuelve_422(self, client):
        respuesta = client.post(URL, json=_payload(razon_social="   "))

        assert respuesta.status_code == 422


class TestListarClientes:
    def test_lista_vacia_al_inicio(self, client):
        respuesta = client.get(URL)

        assert respuesta.status_code == 200
        assert respuesta.json() == []

    def test_lista_incluye_clientes_creados(self, client):
        client.post(URL, json=_payload())
        client.post(URL, json=_payload(cuit_cuil="20999999999", razon_social="Beta SRL"))

        respuesta = client.get(URL)

        assert respuesta.status_code == 200
        assert len(respuesta.json()) == 2

    def test_filtro_por_estado(self, client):
        client.post(URL, json=_payload(estado_general="activo"))
        creado = client.post(
            URL, json=_payload(cuit_cuil="20999999999", estado_general="inactivo")
        ).json()

        respuesta = client.get(URL, params={"estado": "inactivo"})

        assert respuesta.status_code == 200
        ids = [c["id"] for c in respuesta.json()]
        assert ids == [creado["id"]]


class TestObtenerCliente:
    def test_obtener_cliente_existente(self, client):
        creado = client.post(URL, json=_payload()).json()

        respuesta = client.get(f"{URL}{creado['id']}")

        assert respuesta.status_code == 200
        assert respuesta.json()["id"] == creado["id"]

    def test_obtener_cliente_inexistente_devuelve_404(self, client):
        respuesta = client.get(f"{URL}99999")

        assert respuesta.status_code == 404


class TestActualizarCliente:
    def test_actualizacion_parcial(self, client):
        creado = client.post(URL, json=_payload()).json()

        respuesta = client.patch(
            f"{URL}{creado['id']}", json={"telefono": "+54 11 0000-0000"}
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["telefono"] == "+54 11 0000-0000"
        assert respuesta.json()["razon_social"] == "ACME S.A."

    def test_actualizar_cliente_inexistente_devuelve_404(self, client):
        respuesta = client.patch(f"{URL}99999", json={"telefono": "123"})

        assert respuesta.status_code == 404

    def test_actualizar_a_cuit_duplicado_devuelve_409(self, client):
        client.post(URL, json=_payload())
        otro = client.post(URL, json=_payload(cuit_cuil="20999999999")).json()

        respuesta = client.patch(f"{URL}{otro['id']}", json={"cuit_cuil": "20123456789"})

        assert respuesta.status_code == 409


class TestEliminarCliente:
    def test_eliminar_cliente_existente_devuelve_204(self, client):
        creado = client.post(URL, json=_payload()).json()

        respuesta = client.delete(f"{URL}{creado['id']}")

        assert respuesta.status_code == 204
        assert client.get(f"{URL}{creado['id']}").status_code == 404

    def test_eliminar_cliente_inexistente_devuelve_404(self, client):
        respuesta = client.delete(f"{URL}99999")

        assert respuesta.status_code == 404
