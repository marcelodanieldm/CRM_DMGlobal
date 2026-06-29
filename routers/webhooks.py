"""
Procesador de webhooks unificado — MercadoPago e Stripe.

Flujo de ambos endpoints:
  1. Verificar firma criptográfica de la pasarela.
  2. Parsear el payload y mapear el estado de la pasarela a nuestro EstadoSuscripcion.
  3. Localizar la Suscripcion: primero por externa_id; fallback por CUIT + pasarela.
  4. Aplicar el cambio de estado y registrar un AuditLog.
  5. Retornar siempre HTTP 200 salvo errores de firma (401) o payload (400),
     para que las pasarelas no reintentan indefinidamente por errores de negocio.
"""

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone

import httpx
import stripe
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import AuditLog, Cliente, Suscripcion
from notifier import notificar_cambio_estado

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# ---------------------------------------------------------------------------
# Configuración (variables de entorno)
# ---------------------------------------------------------------------------

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

_STRIPE_WEBHOOK_SECRET: str = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
_MP_ACCESS_TOKEN: str = os.environ.get("MP_ACCESS_TOKEN", "")
_MP_WEBHOOK_SECRET: str = os.environ.get("MP_WEBHOOK_SECRET", "")

# ---------------------------------------------------------------------------
# Tablas de traducción de estados
# ---------------------------------------------------------------------------

# MercadoPago preapproval.status → EstadoSuscripcion
_MP_STATUS_MAP: dict[str, str] = {
    "authorized": "activa",
    "paused": "pausada",
    "cancelled": "pausada",
}

# Stripe subscription.status → EstadoSuscripcion
_STRIPE_STATUS_MAP: dict[str, str] = {
    "active": "activa",
    "past_due": "pausada",
    "unpaid": "pausada",
    "canceled": "pausada",
    "paused": "pausada",
}

# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _registrar_audit(
    db: Session,
    *,
    suscripcion_id: int | None,
    accion: str,
    detalles: str,
    pasarela: str,
) -> None:
    db.add(
        AuditLog(
            suscripcion_id=suscripcion_id,
            usuario_interno=f"webhook:{pasarela}",
            accion=accion,
            detalles=detalles,
        )
    )


def _cambiar_estado(
    db: Session,
    suscripcion: Suscripcion,
    nuevo_estado: str,
    *,
    pasarela: str,
    detalles: str,
) -> None:
    estado_anterior = suscripcion.estado_suscripcion
    if estado_anterior == nuevo_estado:
        # Idempotencia: registrar igual para trazabilidad, pero no dirty-write
        _registrar_audit(
            db=db,
            suscripcion_id=suscripcion.id,
            accion=f"estado_sin_cambio:{nuevo_estado}",
            detalles=detalles,
            pasarela=pasarela,
        )
        db.commit()
        return

    suscripcion.estado_suscripcion = nuevo_estado
    if nuevo_estado == "pausada":
        suscripcion.fecha_ultima_pausa = datetime.now(timezone.utc)

    _registrar_audit(
        db=db,
        suscripcion_id=suscripcion.id,
        accion=f"estado:{estado_anterior}→{nuevo_estado}",
        detalles=detalles,
        pasarela=pasarela,
    )
    db.commit()


def _buscar_suscripcion(
    db: Session,
    *,
    externa_id: str | None,
    cuit: str | None,
    pasarela: str,
) -> Suscripcion | None:
    """Localiza una Suscripcion activa/pausada.

    Estrategia doble para máxima robustez:
      1. Por externa_id (match exacto con el ID de la pasarela).
      2. Por CUIT del cliente + pasarela (útil cuando externa_id aún no fue guardado).
    """
    if externa_id:
        found = db.scalars(
            select(Suscripcion).where(Suscripcion.externa_id == externa_id)
        ).first()
        if found:
            return found

    if cuit:
        cliente = db.scalars(
            select(Cliente).where(Cliente.cuit_cuil == cuit)
        ).first()
        if cliente:
            return db.scalars(
                select(Suscripcion).where(
                    Suscripcion.cliente_id == cliente.id,
                    Suscripcion.pasarela_pago == pasarela,
                    Suscripcion.estado_suscripcion != "desactivada",
                )
            ).first()

    return None


# ---------------------------------------------------------------------------
# MercadoPago — verificación de firma y fetch de preaprobación
# ---------------------------------------------------------------------------


def _verificar_firma_mp(
    *,
    x_signature: str,
    x_request_id: str,
    data_id: str,
) -> bool:
    """Verifica la firma HMAC-SHA256 enviada por MercadoPago.

    MP firma el manifest: "id:<data_id>;request-id:<x_request_id>;ts:<ts>;"
    La cabecera x-signature tiene el formato: "ts=<timestamp>,v1=<hex_digest>"
    """
    if not _MP_WEBHOOK_SECRET:
        logger.warning("MP_WEBHOOK_SECRET no configurado — verificación omitida (solo dev)")
        return True  # cambiar a False en producción sin secret configurado

    parts = dict(p.split("=", 1) for p in x_signature.split(",") if "=" in p)
    ts = parts.get("ts", "")
    v1 = parts.get("v1", "")
    if not ts or not v1:
        return False

    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
    expected = hmac.new(
        _MP_WEBHOOK_SECRET.encode(),
        manifest.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, v1)


async def _fetch_mp_preapproval(sub_id: str) -> dict | None:
    """Consulta la API de MercadoPago para obtener el detalle de una suscripción.

    La API devuelve, entre otros campos:
      - status:             authorized | paused | cancelled | pending
      - external_reference: valor libre que nosotros llenamos con el CUIT
      - id:                 ID de la preaprobación en MP
    """
    url = f"https://api.mercadopago.com/preapproval/{sub_id}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {_MP_ACCESS_TOKEN}"},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            logger.error("Error al consultar MP API (sub_id=%s): %s", sub_id, exc)
            return None


# ---------------------------------------------------------------------------
# Endpoint: POST /webhooks/mercadopago
# ---------------------------------------------------------------------------


@router.post("/mercadopago")
async def webhook_mercadopago(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_signature: str | None = Header(default=None, alias="x-signature"),
    x_request_id: str | None = Header(default=None, alias="x-request-id"),
) -> dict:
    body_bytes = await request.body()

    try:
        payload: dict = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cuerpo JSON inválido",
        )

    event_type: str = payload.get("type", "")
    data_id: str = str(payload.get("data", {}).get("id", ""))

    # 1. Verificar firma si viene la cabecera
    if x_signature:
        if not _verificar_firma_mp(
            x_signature=x_signature,
            x_request_id=x_request_id or "",
            data_id=data_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Firma de MercadoPago inválida",
            )

    logger.info("MP webhook recibido | type=%s data_id=%s", event_type, data_id)

    # 2. Filtrar únicamente eventos de suscripción relevantes
    if event_type not in ("subscription_preapproval", "subscription_authorized"):
        return {"detail": "evento_ignorado", "type": event_type}

    if not data_id:
        return {"detail": "sin_data_id"}

    # 3. Obtener detalle completo desde MP API (IPN solo envía el ID)
    mp_sub = await _fetch_mp_preapproval(data_id)
    if not mp_sub:
        # Retornamos 200 para que MP no reintente; el error quedó en logs
        return {"detail": "error_api_mp", "sub_id": data_id}

    mp_status: str = mp_sub.get("status", "")
    # external_reference es el campo libre que llenamos con el CUIT al crear la suscripción
    cuit: str = mp_sub.get("external_reference", "")
    mp_sub_id: str = str(mp_sub.get("id", data_id))

    # 4. Mapear estado de MP a nuestro dominio
    nuevo_estado = _MP_STATUS_MAP.get(mp_status)
    if nuevo_estado is None:
        logger.info("MP status '%s' no requiere acción", mp_status)
        return {"detail": "estado_ignorado", "mp_status": mp_status}

    # 5. Localizar suscripción
    suscripcion = _buscar_suscripcion(
        db,
        externa_id=mp_sub_id,
        cuit=cuit,
        pasarela="mercadopago",
    )
    if not suscripcion:
        logger.warning(
            "Suscripción MP no encontrada | externa_id=%s cuit=%s",
            mp_sub_id, cuit,
        )
        return {"detail": "suscripcion_no_encontrada"}

    # 6. Aplicar cambio de estado + AuditLog
    # Capturar nombre del servicio ANTES del commit (la sesión expira atributos tras commit)
    nombre_servicio: str = suscripcion.servicio.nombre
    suscripcion_id: int = suscripcion.id

    _cambiar_estado(
        db,
        suscripcion,
        nuevo_estado,
        pasarela="mercadopago",
        detalles=(
            f"type={event_type} mp_status={mp_status} "
            f"sub_id={mp_sub_id} cuit={cuit}"
        ),
    )

    # Notificar en background tras el commit exitoso
    background_tasks.add_task(
        notificar_cambio_estado,
        cuit=cuit,
        nombre_servicio=nombre_servicio,
        nuevo_estado=nuevo_estado,
        pasarela="mercadopago",
        suscripcion_id=suscripcion_id,
    )

    logger.info(
        "Suscripción %d → '%s' (vía MercadoPago)",
        suscripcion_id, nuevo_estado,
    )
    return {"detail": "ok", "suscripcion_id": suscripcion_id, "nuevo_estado": nuevo_estado}


# ---------------------------------------------------------------------------
# Endpoint: POST /webhooks/stripe
# ---------------------------------------------------------------------------


@router.post("/stripe")
async def webhook_stripe(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
) -> dict:
    body_bytes = await request.body()

    if not stripe_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cabecera stripe-signature requerida",
        )

    # 1. Verificar firma de Stripe (SDK verifica timestamp + HMAC-SHA256)
    try:
        event = stripe.Webhook.construct_event(
            payload=body_bytes,
            sig_header=stripe_signature,
            secret=_STRIPE_WEBHOOK_SECRET,
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firma de Stripe inválida",
        )
    except Exception as exc:
        logger.error("Error construyendo evento Stripe: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload de Stripe inválido",
        )

    logger.info("Stripe webhook recibido | type=%s id=%s", event["type"], event["id"])

    # 2. Filtrar eventos procesables
    _EVENTOS_STRIPE = {"customer.subscription.updated", "customer.subscription.deleted"}
    if event["type"] not in _EVENTOS_STRIPE:
        return {"detail": "evento_ignorado", "type": event["type"]}

    stripe_sub: dict = event["data"]["object"]
    stripe_status: str = stripe_sub.get("status", "")
    stripe_sub_id: str = stripe_sub.get("id", "")
    # El CUIT se guarda en metadata al crear la suscripción en Stripe
    metadata: dict = stripe_sub.get("metadata", {})
    cuit: str = metadata.get("cuit_cuil", "")

    # 3. Mapear estado de Stripe a nuestro dominio
    # customer.subscription.deleted es una baja permanente → "desactivada"
    if event["type"] == "customer.subscription.deleted":
        nuevo_estado: str | None = "desactivada"
    else:
        nuevo_estado = _STRIPE_STATUS_MAP.get(stripe_status)

    if nuevo_estado is None:
        logger.info("Stripe status '%s' no requiere acción", stripe_status)
        return {"detail": "estado_ignorado", "stripe_status": stripe_status}

    # 4. Localizar suscripción
    suscripcion = _buscar_suscripcion(
        db,
        externa_id=stripe_sub_id,
        cuit=cuit,
        pasarela="stripe",
    )
    if not suscripcion:
        logger.warning(
            "Suscripción Stripe no encontrada | sub_id=%s cuit=%s",
            stripe_sub_id, cuit,
        )
        return {"detail": "suscripcion_no_encontrada"}

    # 5. Aplicar cambio de estado + AuditLog
    # Capturar nombre del servicio ANTES del commit (la sesión expira atributos tras commit)
    nombre_servicio: str = suscripcion.servicio.nombre
    suscripcion_id: int = suscripcion.id

    _cambiar_estado(
        db,
        suscripcion,
        nuevo_estado,
        pasarela="stripe",
        detalles=(
            f"event_type={event['type']} event_id={event['id']} "
            f"stripe_status={stripe_status} sub_id={stripe_sub_id} cuit={cuit}"
        ),
    )

    # Notificar en background tras el commit exitoso
    background_tasks.add_task(
        notificar_cambio_estado,
        cuit=cuit,
        nombre_servicio=nombre_servicio,
        nuevo_estado=nuevo_estado,
        pasarela="stripe",
        suscripcion_id=suscripcion_id,
    )

    logger.info(
        "Suscripción %d → '%s' (vía Stripe)",
        suscripcion_id, nuevo_estado,
    )
    return {"detail": "ok", "suscripcion_id": suscripcion_id, "nuevo_estado": nuevo_estado}
