"""
Tests del router de autenticación (routers/login.py).

Endpoints:
  POST /api/v1/auth/login              login con OAuth2PasswordRequestForm
  POST /api/v1/auth/usuarios           alta de usuario (solo admin)
  GET  /api/v1/auth/usuarios           listado de usuarios (solo admin)
  PUT  /api/v1/auth/usuarios/{id}      actualización (solo admin)
"""
LOGIN_URL = "/api/v1/auth/login"
USUARIOS_URL = "/api/v1/auth/usuarios"


class TestLogin:
    def test_credenciales_correctas_devuelve_token(self, client, crear_usuario):
        crear_usuario(username="ana", password="ClaveSegura1", rol="soporte")

        respuesta = client.post(
            LOGIN_URL, data={"username": "ana", "password": "ClaveSegura1"}
        )

        assert respuesta.status_code == 200
        data = respuesta.json()
        assert data["token_type"] == "bearer"
        assert "access_token" in data

    def test_password_incorrecta_devuelve_401(self, client, crear_usuario):
        crear_usuario(username="ana", password="ClaveSegura1")

        respuesta = client.post(
            LOGIN_URL, data={"username": "ana", "password": "incorrecta"}
        )

        assert respuesta.status_code == 401

    def test_usuario_inexistente_devuelve_401(self, client):
        respuesta = client.post(
            LOGIN_URL, data={"username": "fantasma", "password": "loquesea"}
        )

        assert respuesta.status_code == 401

    def test_usuario_inactivo_devuelve_401(self, client, crear_usuario):
        crear_usuario(username="ana", password="ClaveSegura1", activo=False)

        respuesta = client.post(
            LOGIN_URL, data={"username": "ana", "password": "ClaveSegura1"}
        )

        assert respuesta.status_code == 401


class TestCrearUsuario:
    def test_admin_puede_crear_usuario(self, client, admin_headers):
        respuesta = client.post(
            USUARIOS_URL,
            json={
                "username": "nuevo",
                "email": "nuevo@test.com",
                "password": "ClaveNueva1",
                "rol": "soporte",
            },
            headers=admin_headers,
        )

        assert respuesta.status_code == 201
        assert respuesta.json()["username"] == "nuevo"

    def test_soporte_no_puede_crear_usuario(self, client, soporte_headers):
        respuesta = client.post(
            USUARIOS_URL,
            json={
                "username": "nuevo",
                "email": "nuevo@test.com",
                "password": "ClaveNueva1",
                "rol": "soporte",
            },
            headers=soporte_headers,
        )

        assert respuesta.status_code == 403

    def test_sin_token_devuelve_401(self, client):
        respuesta = client.post(
            USUARIOS_URL,
            json={
                "username": "nuevo",
                "email": "nuevo@test.com",
                "password": "ClaveNueva1",
                "rol": "soporte",
            },
        )

        assert respuesta.status_code == 401

    def test_password_corta_devuelve_422(self, client, admin_headers):
        respuesta = client.post(
            USUARIOS_URL,
            json={
                "username": "nuevo",
                "email": "nuevo@test.com",
                "password": "abc1A",
                "rol": "soporte",
            },
            headers=admin_headers,
        )

        assert respuesta.status_code == 422

    def test_password_sin_numero_devuelve_422(self, client, admin_headers):
        respuesta = client.post(
            USUARIOS_URL,
            json={
                "username": "nuevo",
                "email": "nuevo@test.com",
                "password": "SinNumeros",
                "rol": "soporte",
            },
            headers=admin_headers,
        )

        assert respuesta.status_code == 422

    def test_rol_invalido_devuelve_422(self, client, admin_headers):
        respuesta = client.post(
            USUARIOS_URL,
            json={
                "username": "nuevo",
                "email": "nuevo@test.com",
                "password": "ClaveNueva1",
                "rol": "superadmin",
            },
            headers=admin_headers,
        )

        assert respuesta.status_code == 422


class TestListarUsuarios:
    def test_admin_puede_listar(self, client, admin_headers, crear_usuario):
        crear_usuario(username="otro")

        respuesta = client.get(USUARIOS_URL, headers=admin_headers)

        assert respuesta.status_code == 200
        assert len(respuesta.json()) >= 2  # admin_headers + "otro"

    def test_soporte_no_puede_listar(self, client, soporte_headers):
        respuesta = client.get(USUARIOS_URL, headers=soporte_headers)

        assert respuesta.status_code == 403


class TestActualizarUsuario:
    def test_admin_puede_desactivar_usuario(self, client, admin_headers, crear_usuario):
        usuario = crear_usuario(username="a_desactivar")

        respuesta = client.put(
            f"{USUARIOS_URL}/{usuario.id}",
            json={"activo": False},
            headers=admin_headers,
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["activo"] is False

    def test_actualizar_usuario_inexistente_devuelve_404(self, client, admin_headers):
        respuesta = client.put(
            f"{USUARIOS_URL}/99999", json={"activo": False}, headers=admin_headers
        )

        assert respuesta.status_code == 404

    def test_soporte_no_puede_actualizar(self, client, soporte_headers, crear_usuario):
        usuario = crear_usuario(username="otro2")

        respuesta = client.put(
            f"{USUARIOS_URL}/{usuario.id}",
            json={"activo": False},
            headers=soporte_headers,
        )

        assert respuesta.status_code == 403
