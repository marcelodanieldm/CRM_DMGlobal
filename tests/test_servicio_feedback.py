"""
Tests del endpoint público de validación del Add-on "Servicio de Feedback".

GET /api/v1/servicio-feedback/validar/  (ver routers/servicio_feedback.py)

Casos cubiertos:
  1. Suscripción ACTIVO/DEMO + token correcto -> 200, autorizado=true.
  2. Suscripción INACTIVO + token correcto -> 403.
  3. Token incorrecto / comercio_id inexistente / formato inválido -> 401,
     siempre con el mismo detail genérico (no debe filtrar el motivo real).
  4. Método no permitido (POST) -> 405.
"""
import uuid

URL = "/api/v1/servicio-feedback/validar/"


class TestValidacionExitosa:
    def test_suscripcion_activa_devuelve_200_y_datos_del_comercio(self, client, crear_config):
        config = crear_config(
            estado_suscripcion="ACTIVO",
            tipo_negocio="HOTEL",
            nombre_organizacion="Hotel Paraíso",
        )

        respuesta = client.get(
            URL, params={"comercio_id": str(config.id), "token": str(config.api_token)}
        )

        assert respuesta.status_code == 200
        assert respuesta.json() == {
            "autorizado": True,
            "nombre_comercio": "Hotel Paraíso",
            "tipo_negocio": "HOTEL",
            "google_review_link": config.google_review_link,
        }

    def test_suscripcion_demo_tambien_devuelve_200(self, client, crear_config):
        """DEMO se autoriza igual que ACTIVO según las reglas del endpoint."""
        config = crear_config(estado_suscripcion="DEMO")

        respuesta = client.get(
            URL, params={"comercio_id": str(config.id), "token": str(config.api_token)}
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["autorizado"] is True


class TestSuscripcionInactiva:
    def test_suscripcion_inactiva_devuelve_403(self, client, crear_config):
        config = crear_config(estado_suscripcion="INACTIVO")

        respuesta = client.get(
            URL, params={"comercio_id": str(config.id), "token": str(config.api_token)}
        )

        assert respuesta.status_code == 403


class TestTokenInvalido:
    def test_token_incorrecto_devuelve_401(self, client, crear_config):
        config = crear_config(estado_suscripcion="ACTIVO")

        respuesta = client.get(
            URL, params={"comercio_id": str(config.id), "token": str(uuid.uuid4())}
        )

        assert respuesta.status_code == 401

    def test_comercio_id_inexistente_devuelve_401(self, client):
        respuesta = client.get(
            URL, params={"comercio_id": str(uuid.uuid4()), "token": str(uuid.uuid4())}
        )

        assert respuesta.status_code == 401

    def test_comercio_id_con_formato_invalido_devuelve_401(self, client):
        respuesta = client.get(
            URL, params={"comercio_id": "esto-no-es-un-uuid", "token": "tampoco"}
        )

        assert respuesta.status_code == 401

    def test_401_no_revela_el_motivo_real_del_rechazo(self, client, crear_config):
        """Formato inválido, comercio inexistente y token incorrecto deben dar
        exactamente el mismo 'detail', para no delatar si un comercio_id existe."""
        config = crear_config(estado_suscripcion="ACTIVO")

        respuestas = [
            client.get(URL, params={"comercio_id": "formato-invalido", "token": "x"}),
            client.get(URL, params={"comercio_id": str(uuid.uuid4()), "token": "x"}),
            client.get(URL, params={"comercio_id": str(config.id), "token": "x"}),
        ]

        details = {r.json()["detail"] for r in respuestas}
        assert details == {"Credenciales inválidas"}


class TestMetodoNoPermitido:
    def test_post_devuelve_405(self, client):
        respuesta = client.post(URL)

        assert respuesta.status_code == 405
