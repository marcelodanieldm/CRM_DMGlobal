"""
Tests unitarios de notifier.py — dispatcher de eventos salientes hacia n8n/Zapier.

Se mockea httpx.AsyncClient para no depender de red real.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx

import notifier


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mock_async_client(post_side_effect=None, post_return=None):
    mc = MagicMock()
    mc.__aenter__ = AsyncMock(return_value=mc)
    mc.__aexit__ = AsyncMock(return_value=False)
    if post_side_effect is not None:
        mc.post = AsyncMock(side_effect=post_side_effect)
    else:
        mc.post = AsyncMock(return_value=post_return)
    return mc


def _mock_response(status_code=200):
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.raise_for_status = MagicMock()
    if status_code >= 400:
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=r
        )
    return r


class TestNotificarCambioEstado:
    def test_sin_destinos_configurados_no_hace_requests(self, monkeypatch):
        monkeypatch.setattr(notifier, "_DESTINOS", [])
        cliente_mock = MagicMock()
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: cliente_mock)

        run(notifier.notificar_cambio_estado(
            cuit="20123456789", nombre_servicio="Monitoreo Web",
            nuevo_estado="activa", pasarela="stripe", suscripcion_id=1,
        ))

        cliente_mock.assert_not_called()

    def test_envia_post_a_cada_destino_configurado(self, monkeypatch):
        destinos = ["https://n8n.test/webhook", "https://zapier.test/hook"]
        monkeypatch.setattr(notifier, "_DESTINOS", destinos)
        mc = _mock_async_client(post_return=_mock_response(200))
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mc)

        run(notifier.notificar_cambio_estado(
            cuit="20123456789", nombre_servicio="Monitoreo Web",
            nuevo_estado="pausada", pasarela="mercadopago", suscripcion_id=5,
        ))

        assert mc.post.await_count == 2
        primera_llamada = mc.post.await_args_list[0]
        assert primera_llamada.args[0] == destinos[0]
        payload = primera_llamada.kwargs["json"]
        assert payload["cuit"] == "20123456789"
        assert payload["nuevo_estado"] == "pausada"
        assert payload["suscripcion_id"] == 5

    def test_error_http_en_un_destino_no_interrumpe_los_demas(self, monkeypatch):
        destinos = ["https://falla.test/webhook", "https://ok.test/webhook"]
        monkeypatch.setattr(notifier, "_DESTINOS", destinos)

        respuestas = [_mock_response(500), _mock_response(200)]
        mc = _mock_async_client(post_side_effect=respuestas)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mc)

        # No debe lanzar excepción aunque el primer destino falle.
        run(notifier.notificar_cambio_estado(
            cuit="20123456789", nombre_servicio="Monitoreo Web",
            nuevo_estado="activa", pasarela="stripe", suscripcion_id=1,
        ))

        assert mc.post.await_count == 2

    def test_error_de_red_no_interrumpe_los_demas_destinos(self, monkeypatch):
        destinos = ["https://timeout.test/webhook", "https://ok.test/webhook"]
        monkeypatch.setattr(notifier, "_DESTINOS", destinos)

        mc = _mock_async_client(
            post_side_effect=[httpx.ConnectError("no se pudo conectar"), _mock_response(200)]
        )
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mc)

        run(notifier.notificar_cambio_estado(
            cuit="20123456789", nombre_servicio="Monitoreo Web",
            nuevo_estado="activa", pasarela="stripe", suscripcion_id=1,
        ))

        assert mc.post.await_count == 2
