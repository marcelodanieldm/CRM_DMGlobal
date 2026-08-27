"""
Tests unitarios de bots/bot_guard.py.

Se mockea requests.get para no depender de red real. Estrategia fail-closed:
ante cualquier error, debe negar el acceso (False) o abortar el proceso.
"""
import asyncio

import pytest
import requests

import bots.bot_guard as bot_guard


def _mock_response(json_data: dict, status_code: int = 200):
    class _Resp:
        def raise_for_status(self):
            if status_code >= 400:
                raise requests.exceptions.HTTPError(response=self)

        def json(self):
            return json_data

        status_code_ = status_code

    r = _Resp()
    r.status_code = status_code
    return r


class TestValidarAcceso:
    def test_sin_api_key_configurada_devuelve_false(self, monkeypatch):
        monkeypatch.setattr(bot_guard, "_BOT_API_KEY", "")

        autorizado, estado = bot_guard.validar_acceso("20123456789", "Monitoreo Web")

        assert autorizado is False
        assert estado == "api_key_no_configurada"

    def test_respuesta_exitosa_autorizada(self, monkeypatch):
        monkeypatch.setattr(bot_guard, "_BOT_API_KEY", "clave-valida")
        monkeypatch.setattr(
            requests, "get",
            lambda *a, **kw: _mock_response({"autorizado": True, "estado": "activa"}),
        )

        autorizado, estado = bot_guard.validar_acceso("20123456789", "Monitoreo Web")

        assert autorizado is True
        assert estado == "activa"

    def test_timeout_devuelve_false(self, monkeypatch):
        monkeypatch.setattr(bot_guard, "_BOT_API_KEY", "clave-valida")

        def _raise_timeout(*a, **kw):
            raise requests.exceptions.Timeout()

        monkeypatch.setattr(requests, "get", _raise_timeout)

        autorizado, estado = bot_guard.validar_acceso("20123456789", "Monitoreo Web")

        assert autorizado is False
        assert estado == "timeout"

    def test_connection_error_devuelve_false(self, monkeypatch):
        monkeypatch.setattr(bot_guard, "_BOT_API_KEY", "clave-valida")

        def _raise_conn(*a, **kw):
            raise requests.exceptions.ConnectionError()

        monkeypatch.setattr(requests, "get", _raise_conn)

        autorizado, estado = bot_guard.validar_acceso("20123456789", "Monitoreo Web")

        assert autorizado is False
        assert estado == "connection_error"

    def test_error_inesperado_devuelve_false(self, monkeypatch):
        monkeypatch.setattr(bot_guard, "_BOT_API_KEY", "clave-valida")

        def _raise(*a, **kw):
            raise ValueError("boom")

        monkeypatch.setattr(requests, "get", _raise)

        autorizado, estado = bot_guard.validar_acceso("20123456789", "Monitoreo Web")

        assert autorizado is False
        assert estado == "error_inesperado"


class TestVerificarLicenciaDmGlobal:
    def test_autorizado_devuelve_true(self, monkeypatch):
        monkeypatch.setattr(
            bot_guard, "validar_acceso", lambda cuit, servicio: (True, "activa")
        )

        assert bot_guard.verificar_licencia_dm_global("20123456789", "Monitoreo Web") is True

    def test_no_autorizado_termina_el_proceso_con_exit_0(self, monkeypatch):
        monkeypatch.setattr(
            bot_guard, "validar_acceso", lambda cuit, servicio: (False, "pausada")
        )

        with pytest.raises(SystemExit) as exc_info:
            bot_guard.verificar_licencia_dm_global("20123456789", "Monitoreo Web")

        assert exc_info.value.code == 0


class TestAbortarSiNoAutorizado:
    def test_autorizado_no_hace_nada(self, monkeypatch):
        monkeypatch.setattr(
            bot_guard, "validar_acceso", lambda cuit, servicio: (True, "activa")
        )

        assert bot_guard.abortar_si_no_autorizado("20123456789", "Monitoreo Web") is None

    def test_no_autorizado_termina_el_proceso_con_exit_1(self, monkeypatch):
        monkeypatch.setattr(
            bot_guard, "validar_acceso", lambda cuit, servicio: (False, "desactivada")
        )

        with pytest.raises(SystemExit) as exc_info:
            bot_guard.abortar_si_no_autorizado("20123456789", "Monitoreo Web")

        assert exc_info.value.code == 1


class TestRequiereSuscripcionActiva:
    def test_decorador_sync_ejecuta_la_funcion_si_esta_autorizado(self, monkeypatch):
        monkeypatch.setattr(
            bot_guard, "validar_acceso", lambda cuit, servicio: (True, "activa")
        )

        @bot_guard.requiere_suscripcion_activa(cuit="20123456789", nombre_servicio="Monitoreo Web")
        def tarea():
            return "ejecutado"

        assert tarea() == "ejecutado"

    def test_decorador_sync_aborta_si_no_esta_autorizado(self, monkeypatch):
        monkeypatch.setattr(
            bot_guard, "validar_acceso", lambda cuit, servicio: (False, "pausada")
        )

        @bot_guard.requiere_suscripcion_activa(cuit="20123456789", nombre_servicio="Monitoreo Web")
        def tarea():
            return "no debería ejecutarse"

        with pytest.raises(SystemExit):
            tarea()

    def test_decorador_async_ejecuta_la_corrutina_si_esta_autorizado(self, monkeypatch):
        monkeypatch.setattr(
            bot_guard, "validar_acceso", lambda cuit, servicio: (True, "activa")
        )

        @bot_guard.requiere_suscripcion_activa(cuit="20123456789", nombre_servicio="Monitoreo Web")
        async def tarea():
            return "ejecutado"

        resultado = asyncio.new_event_loop().run_until_complete(tarea())
        assert resultado == "ejecutado"
