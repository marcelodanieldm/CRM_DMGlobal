"""
Tests del router de Webhooks (routers/webhooks.py) — MercadoPago y Stripe.

Se mockean las llamadas salientes reales (fetch a la API de MP y la
verificación de firma de Stripe) para no depender de red ni de credenciales
reales. La notificación saliente (notifier.notificar_cambio_estado) no
requiere mock: OUTGOING_WEBHOOK_URLS no está configurada en el entorno de
test, así que retorna inmediatamente sin hacer requests.
"""
import hashlib
import hmac
from unittest.mock import AsyncMock

import stripe

import routers.webhooks as webhooks_router
from models import Cliente, Servicio, Suscripcion

MP_URL = "/webhooks/mercadopago"
STRIPE_URL = "/webhooks/stripe"
MP_SECRET = webhooks_router._MP_WEBHOOK_SECRET


def _firma_mp_valida(data_id: str, x_request_id: str = "req-1", ts: str = "1700000000") -> str:
    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
    digest = hmac.new(MP_SECRET.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return f"ts={ts},v1={digest}"


def _crear_cliente(db_session, cuit="20123456789"):
    cliente = Cliente(razon_social="Cliente Webhook", cuit_cuil=cuit)
    db_session.add(cliente)
    db_session.commit()
    db_session.refresh(cliente)
    return cliente


def _crear_servicio(db_session, nombre="Monitoreo Web"):
    servicio = Servicio(
        nombre=nombre, precio_base=10000.0, moneda="ARS",
        tipo_ejecucion="mensual", tipo_servicio="bot", activo=True,
    )
    db_session.add(servicio)
    db_session.commit()
    db_session.refresh(servicio)
    return servicio


def _crear_suscripcion(db_session, cliente, servicio, pasarela, estado="pausada", externa_id=None):
    sub = Suscripcion(
        cliente_id=cliente.id, servicio_id=servicio.id,
        estado_suscripcion=estado, pasarela_pago=pasarela, externa_id=externa_id,
    )
    db_session.add(sub)
    db_session.commit()
    db_session.refresh(sub)
    return sub


class TestWebhookMercadoPago:
    def test_firma_invalida_devuelve_401(self, client):
        respuesta = client.post(
            MP_URL,
            json={"type": "subscription_preapproval", "data": {"id": "mp-1"}},
            headers={"x-signature": "ts=1,v1=firma-incorrecta", "x-request-id": "req-1"},
        )

        assert respuesta.status_code == 401

    def test_sin_cabecera_de_firma_no_bloquea(self, client):
        """Si no viene x-signature, la verificación se omite (comportamiento
        documentado en _verificar_firma_mp: solo valida si la cabecera está)."""
        respuesta = client.post(
            MP_URL,
            json={"type": "evento_no_relevante", "data": {"id": "mp-1"}},
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["detail"] == "evento_ignorado"

    def test_tipo_de_evento_no_relevante_se_ignora(self, client):
        respuesta = client.post(
            MP_URL,
            json={"type": "payment.created", "data": {"id": "mp-1"}},
            headers={"x-signature": _firma_mp_valida("mp-1"), "x-request-id": "req-1"},
        )

        assert respuesta.status_code == 200
        assert respuesta.json() == {"detail": "evento_ignorado", "type": "payment.created"}

    def test_sin_data_id_devuelve_sin_data_id(self, client):
        respuesta = client.post(
            MP_URL,
            json={"type": "subscription_preapproval", "data": {}},
            headers={"x-signature": _firma_mp_valida(""), "x-request-id": "req-1"},
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["detail"] == "sin_data_id"

    def test_error_al_consultar_api_de_mp_devuelve_200_con_detalle(self, client, monkeypatch):
        monkeypatch.setattr(
            webhooks_router, "_fetch_mp_preapproval", AsyncMock(return_value=None)
        )

        respuesta = client.post(
            MP_URL,
            json={"type": "subscription_preapproval", "data": {"id": "mp-1"}},
            headers={"x-signature": _firma_mp_valida("mp-1"), "x-request-id": "req-1"},
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["detail"] == "error_api_mp"

    def test_status_de_mp_no_mapeado_se_ignora(self, client, monkeypatch):
        monkeypatch.setattr(
            webhooks_router, "_fetch_mp_preapproval",
            AsyncMock(return_value={"status": "pending", "external_reference": "cuit", "id": "mp-1"}),
        )

        respuesta = client.post(
            MP_URL,
            json={"type": "subscription_preapproval", "data": {"id": "mp-1"}},
            headers={"x-signature": _firma_mp_valida("mp-1"), "x-request-id": "req-1"},
        )

        assert respuesta.json() == {"detail": "estado_ignorado", "mp_status": "pending"}

    def test_suscripcion_no_encontrada(self, client, monkeypatch):
        monkeypatch.setattr(
            webhooks_router, "_fetch_mp_preapproval",
            AsyncMock(return_value={"status": "authorized", "external_reference": "99999999999", "id": "mp-1"}),
        )

        respuesta = client.post(
            MP_URL,
            json={"type": "subscription_preapproval", "data": {"id": "mp-1"}},
            headers={"x-signature": _firma_mp_valida("mp-1"), "x-request-id": "req-1"},
        )

        assert respuesta.json()["detail"] == "suscripcion_no_encontrada"

    def test_activa_la_suscripcion_por_externa_id(self, client, monkeypatch, db_session):
        cliente = _crear_cliente(db_session)
        servicio = _crear_servicio(db_session)
        sub = _crear_suscripcion(
            db_session, cliente, servicio, pasarela="mercadopago",
            estado="pausada", externa_id="mp-1",
        )

        monkeypatch.setattr(
            webhooks_router, "_fetch_mp_preapproval",
            AsyncMock(return_value={
                "status": "authorized", "external_reference": cliente.cuit_cuil, "id": "mp-1",
            }),
        )

        respuesta = client.post(
            MP_URL,
            json={"type": "subscription_preapproval", "data": {"id": "mp-1"}},
            headers={"x-signature": _firma_mp_valida("mp-1"), "x-request-id": "req-1"},
        )

        assert respuesta.status_code == 200
        assert respuesta.json() == {
            "detail": "ok", "suscripcion_id": sub.id, "nuevo_estado": "activa",
        }
        db_session.refresh(sub)
        assert sub.estado_suscripcion == "activa"


class TestWebhookStripe:
    def test_sin_cabecera_de_firma_devuelve_401(self, client):
        respuesta = client.post(STRIPE_URL, json={})

        assert respuesta.status_code == 401

    def test_firma_invalida_devuelve_401(self, client, monkeypatch):
        def _raise(*args, **kwargs):
            raise stripe.SignatureVerificationError("firma inválida", "sig")

        monkeypatch.setattr(stripe.Webhook, "construct_event", _raise)

        respuesta = client.post(
            STRIPE_URL, json={}, headers={"stripe-signature": "firma-cualquiera"}
        )

        assert respuesta.status_code == 401

    def test_evento_no_relevante_se_ignora(self, client, monkeypatch):
        evento = {"type": "invoice.paid", "id": "evt_1", "data": {"object": {}}}
        monkeypatch.setattr(stripe.Webhook, "construct_event", lambda **kw: evento)

        respuesta = client.post(
            STRIPE_URL, json={}, headers={"stripe-signature": "firma"}
        )

        assert respuesta.status_code == 200
        assert respuesta.json() == {"detail": "evento_ignorado", "type": "invoice.paid"}

    def test_suscripcion_cancelada_pasa_a_desactivada(self, client, monkeypatch, db_session):
        cliente = _crear_cliente(db_session)
        servicio = _crear_servicio(db_session)
        sub = _crear_suscripcion(
            db_session, cliente, servicio, pasarela="stripe",
            estado="activa", externa_id="sub_1",
        )

        evento = {
            "type": "customer.subscription.deleted",
            "id": "evt_1",
            "data": {"object": {
                "id": "sub_1", "status": "canceled",
                "metadata": {"cuit_cuil": cliente.cuit_cuil},
            }},
        }
        monkeypatch.setattr(stripe.Webhook, "construct_event", lambda **kw: evento)

        respuesta = client.post(
            STRIPE_URL, json={}, headers={"stripe-signature": "firma"}
        )

        assert respuesta.status_code == 200
        assert respuesta.json() == {
            "detail": "ok", "suscripcion_id": sub.id, "nuevo_estado": "desactivada",
        }
        db_session.refresh(sub)
        assert sub.estado_suscripcion == "desactivada"

    def test_suscripcion_past_due_pasa_a_pausada(self, client, monkeypatch, db_session):
        cliente = _crear_cliente(db_session)
        servicio = _crear_servicio(db_session)
        sub = _crear_suscripcion(
            db_session, cliente, servicio, pasarela="stripe",
            estado="activa", externa_id="sub_2",
        )

        evento = {
            "type": "customer.subscription.updated",
            "id": "evt_2",
            "data": {"object": {
                "id": "sub_2", "status": "past_due",
                "metadata": {"cuit_cuil": cliente.cuit_cuil},
            }},
        }
        monkeypatch.setattr(stripe.Webhook, "construct_event", lambda **kw: evento)

        respuesta = client.post(
            STRIPE_URL, json={}, headers={"stripe-signature": "firma"}
        )

        assert respuesta.json()["nuevo_estado"] == "pausada"

    def test_suscripcion_no_encontrada(self, client, monkeypatch):
        evento = {
            "type": "customer.subscription.updated",
            "id": "evt_3",
            "data": {"object": {
                "id": "sub_inexistente", "status": "active",
                "metadata": {"cuit_cuil": "00000000000"},
            }},
        }
        monkeypatch.setattr(stripe.Webhook, "construct_event", lambda **kw: evento)

        respuesta = client.post(
            STRIPE_URL, json={}, headers={"stripe-signature": "firma"}
        )

        assert respuesta.json()["detail"] == "suscripcion_no_encontrada"
