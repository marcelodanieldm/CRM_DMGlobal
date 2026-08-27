"""
Tests unitarios del módulo auth.py.

Cobertura:
  hash_password / verify_password  — hashing bcrypt real (sin mocks)
  crear_token                      — payload del JWT (sub, rol, exp)
  get_usuario_actual                — 401 en todos los casos de token inválido
  require_admin / require_admin_o_soporte — RBAC por rol
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt

import auth


class TestHashPassword:
    def test_hash_no_es_igual_a_la_contrasena_plana(self):
        hashed = auth.hash_password("MiClave123")

        assert hashed != "MiClave123"

    def test_verify_password_acepta_la_contrasena_correcta(self):
        hashed = auth.hash_password("MiClave123")

        assert auth.verify_password("MiClave123", hashed) is True

    def test_verify_password_rechaza_la_contrasena_incorrecta(self):
        hashed = auth.hash_password("MiClave123")

        assert auth.verify_password("OtraClave456", hashed) is False


class TestCrearToken:
    def test_token_contiene_sub_y_rol(self):
        token = auth.crear_token(username="ana", rol="admin")

        payload = jwt.decode(token, auth._SECRET_KEY, algorithms=[auth._ALGORITHM])

        assert payload["sub"] == "ana"
        assert payload["rol"] == "admin"
        assert "exp" in payload

    def test_token_expira_en_el_futuro(self):
        token = auth.crear_token(username="ana", rol="soporte")

        payload = jwt.decode(token, auth._SECRET_KEY, algorithms=[auth._ALGORITHM])
        expiracion = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

        assert expiracion > datetime.now(timezone.utc)

    def test_sin_secret_key_lanza_runtime_error(self, monkeypatch):
        monkeypatch.setattr(auth, "_SECRET_KEY", "")

        with pytest.raises(RuntimeError):
            auth.crear_token(username="ana", rol="admin")


class TestGetUsuarioActual:
    def test_token_valido_devuelve_el_usuario(self, db_session, crear_usuario):
        usuario = crear_usuario(username="valida", rol="soporte")
        token = auth.crear_token(username=usuario.username, rol=usuario.rol)

        resultado = auth.get_usuario_actual(token=token, db=db_session)

        assert resultado.id == usuario.id

    def test_token_malformado_lanza_401(self, db_session):
        with pytest.raises(HTTPException) as exc_info:
            auth.get_usuario_actual(token="esto-no-es-un-jwt", db=db_session)

        assert exc_info.value.status_code == 401

    def test_usuario_inexistente_lanza_401(self, db_session):
        token = auth.crear_token(username="fantasma", rol="admin")

        with pytest.raises(HTTPException) as exc_info:
            auth.get_usuario_actual(token=token, db=db_session)

        assert exc_info.value.status_code == 401

    def test_usuario_inactivo_lanza_401(self, db_session, crear_usuario):
        usuario = crear_usuario(username="inactivo", rol="soporte", activo=False)
        token = auth.crear_token(username=usuario.username, rol=usuario.rol)

        with pytest.raises(HTTPException) as exc_info:
            auth.get_usuario_actual(token=token, db=db_session)

        assert exc_info.value.status_code == 401

    def test_token_expirado_lanza_401(self, db_session, crear_usuario, monkeypatch):
        usuario = crear_usuario(username="expirado", rol="admin")
        token_expirado = jwt.encode(
            {
                "sub": usuario.username,
                "rol": usuario.rol,
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
            auth._SECRET_KEY,
            algorithm=auth._ALGORITHM,
        )

        with pytest.raises(HTTPException) as exc_info:
            auth.get_usuario_actual(token=token_expirado, db=db_session)

        assert exc_info.value.status_code == 401

    def test_sin_secret_key_configurada_lanza_401(self, db_session, monkeypatch):
        monkeypatch.setattr(auth, "_SECRET_KEY", "")

        with pytest.raises(HTTPException) as exc_info:
            auth.get_usuario_actual(token="cualquier-token", db=db_session)

        assert exc_info.value.status_code == 401


class TestRequireAdmin:
    def test_admin_pasa_la_validacion(self, crear_usuario):
        usuario = crear_usuario(username="admin1", rol="admin")

        assert auth.require_admin(usuario) is usuario

    def test_soporte_lanza_403(self, crear_usuario):
        usuario = crear_usuario(username="soporte1", rol="soporte")

        with pytest.raises(HTTPException) as exc_info:
            auth.require_admin(usuario)

        assert exc_info.value.status_code == 403


class TestRequireAdminOSoporte:
    @pytest.mark.parametrize("rol", ["admin", "soporte"])
    def test_admin_y_soporte_pasan_la_validacion(self, crear_usuario, rol):
        usuario = crear_usuario(username=f"user_{rol}", rol=rol)

        assert auth.require_admin_o_soporte(usuario) is usuario
