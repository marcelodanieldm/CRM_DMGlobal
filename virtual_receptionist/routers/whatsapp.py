"""
WhatsApp Router — Recepcionista Virtual Nocturno.

Implementa el webhook de WhatsApp Business Cloud API (Meta).

Endpoints:
    GET  /webhook  ← verificación de token al configurar el webhook en Meta
    POST /webhook  ← recepción de mensajes entrantes de huéspedes

Flujo POST — pipeline de 5 pasos (corre en background):
    a) check_subscription   → CRM DM Global   (¿suscripción activa?)
    b) get_hotel_rules      → Google Drive     (contexto del PDF del hotel)
    c) generate_response    → Gemini Flash     (respuesta de IA)
    d) Detección emergencia → logging.warning  ('[EMERGENCIA]' → alerta)
    e) Enviar respuesta     → WhatsApp Cloud API

Diseño de retorno HTTP:
    GET: retorna el hub.challenge (int) para que Meta confirme la URL.
    POST: retorna Response(status_code=200) SIEMPRE e INMEDIATAMENTE,
          antes de que el pipeline termine. Meta requiere 200 en < 15s;
          el pipeline corre en BackgroundTask para no bloquear.

Seguridad:
    GET:  hmac.compare_digest del hub.verify_token (tiempo constante).
    POST: validación opcional de firma X-Hub-Signature-256.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from virtual_receptionist.config import settings
from virtual_receptionist.services.ai_service import (
    EMERGENCIA_TAG,
    generate_response,
    clasificar_ticket,
    es_emergencia,
    detectar_emergencia_en_mensaje,
)
from virtual_receptionist.services.crm_service import check_subscription
from virtual_receptionist.services.drive_service import get_hotel_rules
from virtual_receptionist.services.sheets_service import (
    EstadoEstadia,
    ContextoChat,
    get_guest_state,
    update_stay_status,
    update_chat_context,
    update_guest_idioma,
    registrar_ticket,
)
from virtual_receptionist.services import whatsapp_service
from virtual_receptionist.services.whatsapp_service import (
    BotonesIdioma,
    BotonesMenu,
    PROMPT_INSTRUCCIONES_CHECKOUT,
    PROMPT_POLITICA_LATE_CHECKOUT,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/recepcionista/whatsapp",
    tags=["recepcionista-virtual"],
)

# ─────────────────────────────────────────────────────────────────────────────
# Modelos Pydantic — estructura del payload de WhatsApp Cloud API
# ─────────────────────────────────────────────────────────────────────────────


class WaText(BaseModel):
    body: str


class WaListReply(BaseModel):
    """Respuesta del usuario a un List Message interactivo."""
    id:          str
    title:       str
    description: str = ""


class WaButtonReply(BaseModel):
    """Respuesta del usuario a botones de respuesta rápida."""
    id:    str
    title: str


class WaInteractive(BaseModel):
    """Payload de un mensaje interactivo (botón o lista seleccionados)."""
    type:         str                          # "list_reply" | "button_reply"
    list_reply:   Optional[WaListReply]   = None
    button_reply: Optional[WaButtonReply] = None

    @property
    def button_id(self) -> str:
        """Retorna el ID del botón/opción seleccionado."""
        if self.list_reply:
            return self.list_reply.id
        if self.button_reply:
            return self.button_reply.id
        return ""


class WaMessage(BaseModel):
    id: str
    from_: str = Field(alias="from")   # "from" es keyword reservada en Python
    type: str
    text:        Optional[WaText]        = None
    interactive: Optional[WaInteractive] = None   # ← nuevo: respuesta a botones

    model_config = {"populate_by_name": True}

    @property
    def es_interactivo(self) -> bool:
        return self.type == "interactive" and self.interactive is not None

    @property
    def button_id(self) -> str:
        """ID del botón seleccionado (vacío si no es interactivo)."""
        return self.interactive.button_id if self.interactive else ""


class WaMetadata(BaseModel):
    display_phone_number: str
    phone_number_id: str              # ID del número receptor (hotel)


class WaValue(BaseModel):
    messaging_product: str = ""
    metadata: Optional[WaMetadata] = None
    messages: Optional[list[WaMessage]] = None


class WaChange(BaseModel):
    value: WaValue
    field: str


class WaEntry(BaseModel):
    id: str
    changes: list[WaChange]


class WaPayload(BaseModel):
    object: str
    entry: list[WaEntry]


# ─────────────────────────────────────────────────────────────────────────────
# Cliente HTTP compartido para enviar mensajes a Meta (inicializado en lifespan)
# ─────────────────────────────────────────────────────────────────────────────

_wa_client: httpx.AsyncClient | None = None


async def init_wa_client() -> None:
    """Inicializa el cliente HTTP para enviar mensajes a la Graph API de Meta."""
    global _wa_client
    _wa_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        headers={
            "Authorization": f"Bearer {settings.whatsapp_access_token}",
            "Content-Type":  "application/json",
        },
    )
    logger.info("WhatsApp: cliente HTTP inicializado.")


async def close_wa_client() -> None:
    """Cierra el cliente HTTP. Llamar en el shutdown de FastAPI."""
    global _wa_client
    if _wa_client:
        await _wa_client.aclose()
        _wa_client = None
        logger.info("WhatsApp: cliente HTTP cerrado.")


# ─────────────────────────────────────────────────────────────────────────────
# GET /webhook — Verificación de token (handshake inicial con Meta)
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/webhook",
    summary="Verificación del webhook — Meta valida la URL del servidor",
    response_description="Retorna hub.challenge como entero si el token coincide.",
)
async def verificar_webhook(
    hub_mode:         str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge:    str = Query(alias="hub.challenge"),
) -> int:
    """Endpoint de verificación del webhook de WhatsApp Business (Meta).

    Meta llama a esta URL con los parámetros de verificación al configurar
    el webhook en el panel de Meta for Developers.  El servidor debe:
      1. Confirmar que ``hub.mode`` es ``"subscribe"``.
      2. Validar ``hub.verify_token`` contra el valor configurado en .env.
      3. Retornar ``hub.challenge`` como número entero para confirmar la URL.

    Usa ``hmac.compare_digest`` para la comparación en tiempo constante
    y evitar timing attacks.

    Args:
        hub_mode:         Debe ser ``"subscribe"``.
        hub_verify_token: Token secreto que Meta envía para verificar.
        hub_challenge:    Número aleatorio que el servidor debe devolver.

    Returns:
        ``int`` — el hub.challenge, señal de que el servidor es legítimo.

    Raises:
        HTTPException 400: si hub.mode no es "subscribe".
        HTTPException 403: si el verify_token no coincide.
    """
    if hub_mode != "subscribe":
        logger.warning("WhatsApp GET: hub.mode=%r (se esperaba 'subscribe').", hub_mode)
        raise HTTPException(status_code=400, detail="hub.mode inválido")

    if not hmac.compare_digest(hub_verify_token, settings.whatsapp_verify_token):
        logger.warning("WhatsApp GET: VERIFY_TOKEN incorrecto — posible solicitud no autorizada.")
        raise HTTPException(status_code=403, detail="verify_token incorrecto")

    logger.info("WhatsApp GET: webhook verificado correctamente.")
    return int(hub_challenge)


# ─────────────────────────────────────────────────────────────────────────────
# POST /webhook — Recepción de mensajes entrantes
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/webhook",
    summary="Recepción de mensajes de WhatsApp — webhook de Meta",
    response_description="Siempre 200 para que Meta no reintente el envío.",
)
async def recibir_mensaje(
    request:          Request,
    background_tasks: BackgroundTasks,
    x_hub_signature:  Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
) -> Response:
    """Recibe el payload JSON de WhatsApp Business Cloud API y orquesta la respuesta.

    Patrón de retorno rápido:
        Meta requiere HTTP 200 en menos de 15 segundos o reintenta el envío.
        Este endpoint valida el payload, lanza el pipeline en BackgroundTasks
        y retorna 200 de inmediato — el procesamiento real corre en background.

    Args:
        request:         Request de FastAPI con el cuerpo JSON de Meta.
        background_tasks: Inyectado por FastAPI para tareas post-respuesta.
        x_hub_signature: Firma HMAC-SHA256 opcional para validar el origen.

    Returns:
        ``Response(status_code=200)`` — siempre, independientemente del resultado.
        Meta no necesita saber si el procesamiento tuvo éxito; solo que lo recibimos.
    """
    body_bytes = await request.body()

    # ── Validación opcional de firma HMAC-SHA256 de Meta ─────────────────────
    if x_hub_signature:
        _validar_firma_meta(body_bytes, x_hub_signature)

    # ── Parsear y validar estructura del payload ──────────────────────────────
    try:
        payload = WaPayload.model_validate_json(body_bytes)
    except Exception as exc:
        logger.warning("WhatsApp POST: payload inválido | %s", exc)
        return Response(status_code=200)   # 200 igual para que Meta no reintente

    if payload.object != "whatsapp_business_account":
        logger.debug("WhatsApp POST: objeto ignorado (%r).", payload.object)
        return Response(status_code=200)

    # ── Extraer datos del mensaje ─────────────────────────────────────────────
    datos = _extraer_datos_mensaje(payload)
    if datos is None:
        # Sin mensaje de texto (imagen, audio, sticker, estado de entrega, etc.)
        return Response(status_code=200)

    numero_wa, texto_mensaje, phone_number_id, message_id, button_id = datos

    logger.info(
        "WhatsApp POST: mensaje | de=%s | phone_id=%s | tipo=%s | texto=%r",
        numero_wa, phone_number_id,
        f"btn:{button_id}" if button_id else "text",
        texto_mensaje[:60],
    )

    # ── Marcar como leído (doble check azul) antes de responder ──────────────
    background_tasks.add_task(_marcar_leido, phone_number_id, message_id)

    # ── Lanzar pipeline en background → responde a Meta de inmediato ─────────
    background_tasks.add_task(
        _procesar_mensaje,
        numero_wa       = numero_wa,
        texto_mensaje   = texto_mensaje,
        phone_number_id = phone_number_id,
        button_id       = button_id,
    )

    return Response(status_code=200)


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline principal (corre en BackgroundTask — post-200)
# ─────────────────────────────────────────────────────────────────────────────



# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE UNIFICADO — árbol de decisión completo (reescritura v2)
# ─────────────────────────────────────────────────────────────────────────────


async def _procesar_mensaje(
    numero_wa:       str,
    texto_mensaje:   str,
    phone_number_id: str,
    button_id:       str = "",
) -> None:
    """Pipeline principal unificado del Recepcionista Virtual.

    Árbol de decisión estricto (se ejecuta en orden; cada rama hace return):

        Paso 1 → get_guest_state()                  Obtener datos del huésped
        ──────────────────────────────────────────────────────────────────────
        Filtro 0  Idioma vacío                   → menú de selección de idioma
                  Botón lang_es/en/pt            → registrar + bienvenida
        ──────────────────────────────────────────────────────────────────────
        Filtro 1  check_subscription()           → corte si suscripción inactiva
        ──────────────────────────────────────────────────────────────────────
        Filtro 2  AWAITING_DNI                   → reiterar formulario pre-checkin
                  AWAITING_TICKET                → procesar ticket + resetear
                  AWAITING_LATE_CHECKOUT_CONFIRM → procesar sí/no late checkout
        ──────────────────────────────────────────────────────────────────────
        Filtro 3  RESERVADO                      → check-in / pre-checkin
                  CHECKED_IN                     → IA con contexto + botones
                  CHECKED_OUT                    → mensaje de despedida
        ──────────────────────────────────────────────────────────────────────
        Fallback  Siempre retorna HTTP 200 a Meta (garantizado en el endpoint)
    """
    import asyncio

    # ── Paso 1: Datos del huésped en Google Sheets ────────────────────────────
    estado = await get_guest_state(numero_wa)

    if estado is None:
        logger.info("Pipeline: huésped %s sin registro en Sheets — IA genérica.", numero_wa)
        await _flujo_ia_general(numero_wa, texto_mensaje, phone_number_id)
        return

    idioma       = estado.get("idioma", "").strip()
    nombre       = estado.get("nombre", "")
    habitacion   = estado.get("habitacion", "")
    pre_ci       = estado.get("pre_checkin_completo", False)
    pin          = estado.get("pin_acceso", "")
    carpeta_id   = estado.get("id_carpeta_drive", "")
    estado_est   = estado.get("estado_estadia",  EstadoEstadia.RESERVADO.value)
    contexto     = estado.get("contexto_chat",   ContextoChat.NORMAL.value)

    logger.info(
        "Pipeline | tel=%s | idioma=%r | estado=%s | ctx=%s | preCI=%s",
        numero_wa, idioma or "∅", estado_est, contexto, pre_ci,
    )

    # ── Filtro 0: Registro de Idioma ──────────────────────────────────────────
    if not idioma:
        if button_id in BotonesIdioma.todos():
            lang = BotonesIdioma.lang_for(button_id)
            await update_guest_idioma(numero_wa, lang)
            logger.info("Filtro0: idioma %s registrado para %s", lang, numero_wa)
            await whatsapp_service.enviar_bienvenida(phone_number_id, numero_wa, nombre, lang)
            await _bienvenida_por_fase(numero_wa, phone_number_id, nombre, lang, estado_est, pre_ci, pin, carpeta_id)
            return

        logger.info("Filtro0: idioma vacío — enviando menú de selección | tel=%s", numero_wa)
        await whatsapp_service.enviar_menu_idioma(phone_number_id, numero_wa)
        return

    # ── Filtro 1: Suscripción activa ──────────────────────────────────────────
    if not await check_subscription(settings.crm_hotel_id):
        logger.warning(
            "Filtro1: suscripción INACTIVA | hotel=%r | tel=%s — mensaje bloqueado.",
            settings.crm_hotel_id, numero_wa,
        )
        return   # Sin respuesta al huésped: no alertar de problemas internos

    # ── Filtro 2: Estados temporales de conversación ──────────────────────────
    if contexto == ContextoChat.AWAITING_DNI.value:
        logger.info("Filtro2: AWAITING_DNI — reiterando formulario | tel=%s", numero_wa)
        form_url = settings.precheckin_form_url or "https://tu-hotel.com/precheckin"
        await _enviar_respuesta(
            phone_number_id, numero_wa,
            _construir_mensaje_precheckin(nombre, idioma, form_url),
        )
        return

    if contexto == ContextoChat.AWAITING_TICKET.value and texto_mensaje.strip():
        logger.info("Filtro2: AWAITING_TICKET — procesando reporte | tel=%s", numero_wa)
        await _manejar_ticket(numero_wa, phone_number_id, texto_mensaje, idioma, habitacion)
        return

    if contexto == ContextoChat.AWAITING_LATE_CHECKOUT_CONFIRM.value and texto_mensaje.strip():
        logger.info("Filtro2: AWAITING_LATE_CHECKOUT_CONFIRM | tel=%s", numero_wa)
        await _manejar_confirmacion_late_checkout(numero_wa, phone_number_id, texto_mensaje, idioma, habitacion)
        return

    # ── Filtro 3a: RESERVADO ──────────────────────────────────────────────────
    if estado_est == EstadoEstadia.RESERVADO.value:
        logger.info("Filtro3: RESERVADO | tel=%s | pre_ci=%s", numero_wa, pre_ci)

        if not pre_ci and contexto != ContextoChat.AWAITING_DNI.value:
            form_url = settings.precheckin_form_url or "https://tu-hotel.com/precheckin"
            await update_chat_context(numero_wa, ContextoChat.AWAITING_DNI)
            await _enviar_respuesta(
                phone_number_id, numero_wa,
                _construir_mensaje_precheckin(nombre, idioma, form_url),
            )
            return

        if texto_mensaje.strip() and detectar_intencion_llegada(texto_mensaje, idioma):
            logger.info("Filtro3: intención de llegada detectada | tel=%s", numero_wa)
            await asyncio.gather(
                update_stay_status(numero_wa, EstadoEstadia.CHECKED_IN),
                update_chat_context(numero_wa, ContextoChat.NORMAL),
            )
            await _enviar_respuesta(
                phone_number_id, numero_wa,
                _construir_mensaje_checkin(nombre, habitacion, pin, carpeta_id, idioma),
            )
            return

        # Consulta general durante reserva → IA básica
        await _flujo_ia_general(numero_wa, texto_mensaje, phone_number_id)
        return

    # ── Filtro 3b: CHECKED_IN ─────────────────────────────────────────────────
    if estado_est == EstadoEstadia.CHECKED_IN.value:
        logger.info("Filtro3: CHECKED_IN | tel=%s | btn=%r", numero_wa, button_id)

        # Botones del menú → handlers dedicados (WiFi, amenities, incidente, consulta)
        if button_id in BotonesMenu.todos():
            await _manejar_boton_menu(numero_wa, phone_number_id, button_id, idioma, habitacion)
            return

        # Texto libre: interceptar checkout y late-checkout antes de IA
        if texto_mensaje.strip():
            if detectar_intencion_checkout(texto_mensaje, idioma):
                await _manejar_checkout(numero_wa, phone_number_id, idioma, habitacion)
                return

            if detectar_intencion_late_checkout(texto_mensaje, idioma):
                await _manejar_late_checkout(numero_wa, phone_number_id, idioma)
                return

            # Texto libre general → IA con contexto enriquecido del huésped
            hotel_context  = await get_hotel_rules()
            guest_context  = _construir_contexto_huesped(estado)
            contexto_total = f"{hotel_context}\n\n{guest_context}"

            respuesta = await generate_response(texto_mensaje, contexto_total)

            if es_emergencia(respuesta):
                logger.warning(
                    "DISPARAR ALERTA TWILIO/TELEGRAM | "
                    "huesped=%s | hab=%s | resp=%r",
                    numero_wa, habitacion, respuesta[:100],
                )

            await _enviar_respuesta(phone_number_id, numero_wa, respuesta)
            return

        # Sin texto ni botón → mostrar menú de estadía
        await whatsapp_service.enviar_menu_estadia(phone_number_id, numero_wa, idioma, nombre)
        return

    # ── Filtro 3c: CHECKED_OUT ────────────────────────────────────────────────
    if estado_est == EstadoEstadia.CHECKED_OUT.value:
        logger.info("Filtro3: CHECKED_OUT | tel=%s", numero_wa)
        await whatsapp_service.enviar_checked_out(
            phone_number_id = phone_number_id,
            to              = numero_wa,
            idioma          = idioma,
            hotel_name      = settings.receptionist_business_name,
        )
        return

    # ── Fallback: estado desconocido ──────────────────────────────────────────
    logger.warning("Pipeline: estado desconocido %r | tel=%s", estado_est, numero_wa)
    await _flujo_ia_general(numero_wa, texto_mensaje, phone_number_id)


# ── Helpers del pipeline unificado ────────────────────────────────────────────


def _construir_contexto_huesped(estado: dict) -> str:
    """Formatea los datos del huésped para inyectarlos en el prompt de Gemini."""
    return (
        "--- DATOS DEL HUÉSPED ---\n"
        f"Nombre:      {estado.get('nombre', 'N/D')}\n"
        f"Habitación:  {estado.get('habitacion', 'N/D')}\n"
        f"Check-in:    {estado.get('fecha_checkin', 'N/D')}\n"
        f"Check-out:   {estado.get('fecha_checkout', 'N/D')}\n"
        f"Idioma:      {estado.get('idioma', 'es')}\n"
        "--- FIN DATOS DEL HUÉSPED ---"
    )


async def _bienvenida_por_fase(
    numero_wa:       str,
    phone_number_id: str,
    nombre:          str,
    idioma:          str,
    estado_est:      str,
    pre_ci:          bool,
    pin:             str,
    carpeta_id:      str,
) -> None:
    """Después de seleccionar idioma, muestra el menú apropiado para la fase actual."""
    if estado_est == EstadoEstadia.CHECKED_IN.value:
        await whatsapp_service.enviar_menu_estadia(phone_number_id, numero_wa, idioma, nombre)
    elif estado_est == EstadoEstadia.RESERVADO.value and pre_ci:
        instrucciones_llegada = {
            "es": "Cuando llegues, escríbeme '✅ Ya llegué' para recibir tu PIN de acceso.",
            "en": "When you arrive, write me '✅ I'm here' to receive your access PIN.",
            "pt": "Quando chegar, me escreva '✅ Cheguei' para receber seu PIN de acesso.",
        }
        await _enviar_respuesta(phone_number_id, numero_wa, instrucciones_llegada.get(idioma, instrucciones_llegada["es"]))
    elif estado_est == EstadoEstadia.CHECKED_OUT.value:
        await whatsapp_service.enviar_checked_out(phone_number_id, numero_wa, idioma, "")


async def _flujo_ia_general(
    numero_huesped:  str,
    texto_mensaje:   str,
    phone_number_id: str,
) -> None:
    """Genera y envía una respuesta con Gemini Flash usando el PDF del hotel."""
    hotel_id = settings.crm_hotel_id
    hotel_context = await get_hotel_rules()
    if not hotel_context:
        hotel_context = "No hay información específica disponible. Responde de forma genérica y profesional."

    respuesta_ia = await generate_response(texto_mensaje, hotel_context)

    if es_emergencia(respuesta_ia):
        logger.warning(
            "DISPARAR ALERTA TWILIO/TELEGRAM | "
            "hotel=%r | huesped=%s | resp=%r",
            hotel_id, numero_huesped, respuesta_ia[:120],
        )
    await _enviar_respuesta(phone_number_id, numero_huesped, respuesta_ia)


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE LEGACY (mantenido para referencia — no se llama desde el endpoint)
# ─────────────────────────────────────────────────────────────────────────────
async def _pipeline_respuesta(
    numero_huesped:  str,
    texto_mensaje:   str,
    phone_number_id: str,
    button_id:       str = "",
) -> None:
    """Orquesta el ciclo de vida del huésped con máquina de estados y fallback IA.

    Pipeline de decisión (en orden de prioridad):
        1. Validar suscripción activa en el CRM             → abortar si inactiva
        2. Consultar estado del huésped en Sheets            → máquina de estados
        3. ESCENARIO 1 — Pre-Check-In pendiente             → link formulario DNI
        4. ESCENARIO 2 — Intención de llegada detectada     → PIN + mapa + habitación
        5. ESCENARIO 3 — CHECKED_IN — botón del menú        → acción según botón
        6. ESCENARIO 3 — CHECKED_IN — AWAITING_TICKET       → clasificar y guardar ticket
        7. ESCENARIO 3 — CHECKED_IN — mensaje normal        → enviar menú interactivo
        8. Fallback: flujo general de IA (Gemini Flash)     → respuesta libre
    """
    import asyncio

    hotel_id = settings.crm_hotel_id

    # ── 1. Validar suscripción ────────────────────────────────────────────────
    if not await check_subscription(hotel_id):
        logger.warning(
            "Pipeline: suscripción INACTIVA | hotel=%r | huesped=%s — ignorado.",
            hotel_id, numero_huesped,
        )
        return

    # ── 2. Estado del huésped en Google Sheets ────────────────────────────────
    estado_raw = await get_guest_state(numero_huesped)

    if estado_raw is None:
        logger.info(
            "Pipeline: huésped %s no encontrado en Sheets — fallback a IA general.",
            numero_huesped,
        )
        await _flujo_ia_general(numero_huesped, texto_mensaje, phone_number_id)
        return

    idioma          = estado_raw.get("idioma", settings.receptionist_default_lang)
    nombre          = estado_raw.get("nombre", "")
    pre_checkin_ok  = estado_raw.get("pre_checkin_completo", False)
    estado_estadia  = estado_raw.get("estado_estadia", EstadoEstadia.RESERVADO.value)
    contexto_chat   = estado_raw.get("contexto_chat", ContextoChat.NORMAL.value)
    habitacion      = estado_raw.get("habitacion", "")
    pin_acceso      = estado_raw.get("pin_acceso", "")
    id_carpeta      = estado_raw.get("id_carpeta_drive", "")

    logger.info(
        "Pipeline: estado=%s | ctx=%s | pre_ci=%s | huesped=%s",
        estado_estadia, contexto_chat, pre_checkin_ok, numero_huesped,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # ESCENARIO 1: Pre-Check-In pendiente
    # El huésped escribe por primera vez antes de llegar y aún no subió
    # su documentación (col G = NO).
    # Acción: interrumpir toda conversación y enviar el link al formulario.
    # ─────────────────────────────────────────────────────────────────────────
    if not pre_checkin_ok and contexto_chat != ContextoChat.AWAITING_DNI.value:
        logger.info(
            "ESCENARIO 1: Pre-CheckIn pendiente | huesped=%s | idioma=%s",
            numero_huesped, idioma,
        )

        form_url = settings.precheckin_form_url or "https://tu-hotel.com/precheckin"
        mensaje  = _construir_mensaje_precheckin(nombre, idioma, form_url)

        # Actualizar estado ANTES de enviar (evita doble mensaje si WhatsApp reintenta)
        await update_chat_context(numero_huesped, ContextoChat.AWAITING_DNI)
        await _enviar_respuesta(phone_number_id, numero_huesped, mensaje)
        return

    # ESCENARIO 1b: El huésped ya estaba en estado AWAITING_DNI y responde algo.
    # Confirmamos que recibimos y lo dejamos en NORMAL hasta que el formulario
    # web actualice automáticamente la col G a SÍ.
    if not pre_checkin_ok and contexto_chat == ContextoChat.AWAITING_DNI.value:
        logger.info(
            "ESCENARIO 1b: AWAITING_DNI — huésped respondió algo | tel=%s",
            numero_huesped,
        )
        confirmacion = _MSG_DNI_RECIBIDO.get(idioma, _MSG_DNI_RECIBIDO["es"])
        await _enviar_respuesta(phone_number_id, numero_huesped, confirmacion)
        return

    # ─────────────────────────────────────────────────────────────────────────
    # ESCENARIO 2: Check-In autónomo (intención de llegada detectada)
    # Pre-CheckIn completado (col G = SÍ) + estado RESERVADO + llega al hotel.
    # Acción: enviar PIN, habitación y link Drive; pasar a CHECKED_IN.
    # ─────────────────────────────────────────────────────────────────────────
    if (
        pre_checkin_ok
        and estado_estadia == EstadoEstadia.RESERVADO.value
        and detectar_intencion_llegada(texto_mensaje, idioma)
    ):
        logger.info(
            "ESCENARIO 2: Check-In autónomo | huesped=%s | hab=%s | idioma=%s",
            numero_huesped, habitacion, idioma,
        )

        mensaje_checkin = _construir_mensaje_checkin(
            nombre     = nombre,
            habitacion = habitacion,
            pin        = pin_acceso,
            carpeta_id = id_carpeta,
            idioma     = idioma,
        )

        # Actualizar estado en paralelo para minimizar latencia
        await asyncio.gather(
            update_stay_status(numero_huesped, EstadoEstadia.CHECKED_IN),
            update_chat_context(numero_huesped, ContextoChat.NORMAL),
        )

        await _enviar_respuesta(phone_number_id, numero_huesped, mensaje_checkin)
        return

    # ─────────────────────────────────────────────────────────────────────────
    # ESCENARIO 3: Huésped CHECKED_IN — menú interactivo, tickets, botones
    # ─────────────────────────────────────────────────────────────────────────
    if estado_estadia == EstadoEstadia.CHECKED_IN.value:
        await _escenario_checked_in(
            numero_huesped  = numero_huesped,
            phone_number_id = phone_number_id,
            button_id       = button_id,
            texto_mensaje   = texto_mensaje,
            idioma          = idioma,
            nombre          = nombre,
            habitacion      = habitacion,
            contexto_chat   = contexto_chat,
        )
        return

    # ─────────────────────────────────────────────────────────────────────────
    # FLUJO GENERAL: IA con contexto PDF del hotel
    # Todos los otros mensajes (preguntas, quejas, conversación normal)
    # van al motor de IA con el contexto de reglas del hotel.
    # ─────────────────────────────────────────────────────────────────────────
    await _flujo_ia_general(numero_huesped, texto_mensaje, phone_number_id)


async def _escenario_checked_in(
    numero_huesped:  str,
    phone_number_id: str,
    button_id:       str,
    texto_mensaje:   str,
    idioma:          str,
    nombre:          str,
    habitacion:      str,
    contexto_chat:   str,
) -> None:
    """Controlador del huésped hospedado (CHECKED_IN).

    Árbol de decisión (en orden de prioridad):
        a) Confirmación late check-out (AWAITING_LATE_CHECKOUT_CONFIRM) → procesar sí/no
        b) Intención de late check-out en texto libre → consultar PDF + preguntar
        c) Intención de check-out en texto libre → instrucciones + CHECKED_OUT
        d) Botón del menú presionado  → acción específica por BotonesMenu.id
        e) Contexto AWAITING_TICKET   → clasificar y guardar el ticket
        f) Mensaje de texto normal    → enviar el menú interactivo
    """
    import asyncio

    # ── a) Confirmación de late check-out pendiente ──────────────────────────
    if contexto_chat == ContextoChat.AWAITING_LATE_CHECKOUT_CONFIRM.value and texto_mensaje.strip():
        logger.info(
            "ESCENARIO 4: confirmación late checkout | huesped=%s | msg=%r",
            numero_huesped, texto_mensaje[:50],
        )
        await _manejar_confirmacion_late_checkout(
            numero_huesped  = numero_huesped,
            phone_number_id = phone_number_id,
            texto_mensaje   = texto_mensaje,
            idioma          = idioma,
            habitacion      = habitacion,
        )
        return

    # ── b) Solicitud de late check-out ────────────────────────────────────────
    if texto_mensaje.strip() and detectar_intencion_late_checkout(texto_mensaje, idioma):
        logger.info(
            "ESCENARIO 4: late checkout detectado | huesped=%s | idioma=%s",
            numero_huesped, idioma,
        )
        await _manejar_late_checkout(
            numero_huesped  = numero_huesped,
            phone_number_id = phone_number_id,
            idioma          = idioma,
        )
        return

    # ── c) Intención de check-out ─────────────────────────────────────────────
    if texto_mensaje.strip() and detectar_intencion_checkout(texto_mensaje, idioma):
        logger.info(
            "ESCENARIO 4: checkout detectado | huesped=%s | hab=%s | idioma=%s",
            numero_huesped, habitacion, idioma,
        )
        from virtual_receptionist.services.sheets_service import get_guest_state as _get_state
        estado_raw = await _get_state(numero_huesped)
        review_link = ""
        if estado_raw:
            # Si el hotel tiene review link en el CRM, lo usamos como cierre
            review_link = estado_raw.get("google_review_link", "")
        await _manejar_checkout(
            numero_huesped  = numero_huesped,
            phone_number_id = phone_number_id,
            idioma          = idioma,
            habitacion      = habitacion,
            review_link     = review_link,
        )
        return

    # ── d) Botón del menú interactivo presionado ─────────────────────────────
    if button_id in BotonesMenu.todos():
        logger.info(
            "ESCENARIO 3: botón presionado | btn=%s | huesped=%s | idioma=%s",
            button_id, numero_huesped, idioma,
        )
        await _manejar_boton_menu(
            numero_huesped  = numero_huesped,
            phone_number_id = phone_number_id,
            button_id       = button_id,
            idioma          = idioma,
            habitacion      = habitacion,
        )
        return

    # ── b) Contexto AWAITING_TICKET: el huésped describe su problema ──────────
    if contexto_chat == ContextoChat.AWAITING_TICKET.value and texto_mensaje.strip():
        logger.info(
            "ESCENARIO 3: ticket recibido | huesped=%s | msg=%r",
            numero_huesped, texto_mensaje[:60],
        )
        await _manejar_ticket(
            numero_huesped  = numero_huesped,
            phone_number_id = phone_number_id,
            texto_mensaje   = texto_mensaje,
            idioma          = idioma,
            habitacion      = habitacion,
        )
        return

    # ── c) Mensaje genérico → mostrar el menú de estadía ─────────────────────
    logger.info(
        "ESCENARIO 3: mostrando menú | huesped=%s | idioma=%s",
        numero_huesped, idioma,
    )
    await whatsapp_service.enviar_menu_estadia(
        phone_number_id = phone_number_id,
        to              = numero_huesped,
        idioma          = idioma,
        nombre          = nombre,
    )


async def _manejar_checkout(
    numero_huesped:  str,
    phone_number_id: str,
    idioma:          str,
    habitacion:      str,
    review_link:     str = "",
) -> None:
    """Procesa el check-out: envía instrucciones del PDF y actualiza el Sheets.

    Flujo:
        1. Consulta el PDF del hotel para obtener las instrucciones de salida.
        2. Actualiza el Estado de Estadía a CHECKED_OUT en el Spreadsheet.
        3. Envía instrucciones de salida + despedida + link de reseña.

    Las dos primeras acciones (obtener instrucciones + actualizar Sheets)
    corren en paralelo para minimizar la latencia.
    """
    import asyncio

    pregunta_checkout = PROMPT_INSTRUCCIONES_CHECKOUT.get(
        idioma, PROMPT_INSTRUCCIONES_CHECKOUT["es"]
    )
    hotel_context = await get_hotel_rules()

    # Consultar PDF e iniciar actualización en paralelo
    instrucciones_task = generate_response(pregunta_checkout, hotel_context)
    checkout_status_task = update_stay_status(numero_huesped, EstadoEstadia.CHECKED_OUT)

    instrucciones, _ = await asyncio.gather(instrucciones_task, checkout_status_task)

    logger.info(
        "CHECKOUT procesado | huesped=%s | hab=%s | instrucciones=%d chars",
        numero_huesped, habitacion, len(instrucciones),
    )

    await whatsapp_service.enviar_checkout_completado(
        phone_number_id = phone_number_id,
        to              = numero_huesped,
        instrucciones   = instrucciones,
        review_link     = review_link,
        idioma          = idioma,
    )


async def _manejar_late_checkout(
    numero_huesped:  str,
    phone_number_id: str,
    idioma:          str,
) -> None:
    """Consulta la política de late checkout en el PDF y pregunta si el huésped desea solicitarlo.

    Flujo:
        1. Extrae la política de late checkout del PDF del hotel con Gemini.
        2. Actualiza el contexto a AWAITING_LATE_CHECKOUT_CONFIRM.
        3. Envía el mensaje con la política + pregunta de confirmación (sí/no).
    """
    import asyncio

    pregunta_late = PROMPT_POLITICA_LATE_CHECKOUT.get(
        idioma, PROMPT_POLITICA_LATE_CHECKOUT["es"]
    )
    hotel_context = await get_hotel_rules()

    # Consultar PDF e iniciar actualización de contexto en paralelo
    politica_task  = generate_response(pregunta_late, hotel_context)
    contexto_task  = update_chat_context(
        numero_huesped, ContextoChat.AWAITING_LATE_CHECKOUT_CONFIRM
    )

    politica_ia, _ = await asyncio.gather(politica_task, contexto_task)

    logger.info(
        "LATE CHECKOUT: política obtenida | huesped=%s | chars=%d",
        numero_huesped, len(politica_ia),
    )

    await whatsapp_service.enviar_late_checkout_pregunta(
        phone_number_id = phone_number_id,
        to              = numero_huesped,
        respuesta_ia    = politica_ia,
        idioma          = idioma,
    )


async def _manejar_confirmacion_late_checkout(
    numero_huesped:  str,
    phone_number_id: str,
    texto_mensaje:   str,
    idioma:          str,
    habitacion:      str,
) -> None:
    """Procesa la respuesta del huésped a la pregunta de late checkout.

    Si el huésped confirma (sí):
        - Registra la solicitud en la pestaña Tickets_Soporte como LATE_CHECKOUT.
        - Envía confirmación de que fue enviada al administrador.

    Si el huésped rechaza (no):
        - Resetea el contexto a NORMAL.
        - Envía mensaje de entendido.

    Si no se puede interpretar:
        - Repite la pregunta.
    """
    import asyncio

    if detectar_afirmacion(texto_mensaje):
        logger.info(
            "LATE CHECKOUT: CONFIRMADO por huesped=%s | hab=%s",
            numero_huesped, habitacion,
        )
        detalle = f"Solicitud de late check-out — habitación {habitacion}"

        await asyncio.gather(
            registrar_ticket(
                numero_huesped = numero_huesped,
                habitacion     = habitacion,
                detalle        = detalle,
                tipo           = "LATE_CHECKOUT",
            ),
            update_chat_context(numero_huesped, ContextoChat.NORMAL),
        )

        await whatsapp_service.enviar_late_checkout_confirmado(
            phone_number_id = phone_number_id,
            to              = numero_huesped,
            idioma          = idioma,
        )

        logger.warning(
            "SOLICITUD LATE CHECKOUT — NOTIFICAR AL HOTELERO | "
            "huesped=%s | hab=%s",
            numero_huesped, habitacion,
        )
        return

    if detectar_negacion(texto_mensaje):
        logger.info(
            "LATE CHECKOUT: cancelado por huesped=%s",
            numero_huesped,
        )
        await update_chat_context(numero_huesped, ContextoChat.NORMAL)
        await whatsapp_service.enviar_late_checkout_cancelado(
            phone_number_id = phone_number_id,
            to              = numero_huesped,
            idioma          = idioma,
        )
        return

    # Respuesta ambigua — repetir la pregunta usando IA
    logger.debug(
        "LATE CHECKOUT: respuesta ambigua | huesped=%s | msg=%r",
        numero_huesped, texto_mensaje[:40],
    )
    await _flujo_ia_general(numero_huesped, texto_mensaje, phone_number_id)


async def _manejar_boton_menu(
    numero_huesped:  str,
    phone_number_id: str,
    button_id:       str,
    idioma:          str,
    habitacion:      str,
) -> None:
    """Ejecuta la acción correspondiente a cada botón del menú de estadía."""

    # ── 📶 Wi-Fi / Clave ─────────────────────────────────────────────────────
    if button_id == BotonesMenu.WIFI:
        hotel_context = await get_hotel_rules()
        pregunta, contexto = whatsapp_service.construir_prompt_wifi(hotel_context, idioma)
        respuesta_wifi = await generate_response(pregunta, contexto)
        await _enviar_respuesta(phone_number_id, numero_huesped, respuesta_wifi)
        return

    # ── 🛏️ Amenities Extras ────────────────────────────────────────────────
    if button_id == BotonesMenu.AMENITIES:
        await update_chat_context(numero_huesped, ContextoChat.AWAITING_TICKET)
        await whatsapp_service.enviar_solicitud_ticket(
            phone_number_id = phone_number_id,
            to              = numero_huesped,
            idioma          = idioma,
        )
        return

    # ── 🛠️ Reportar Incidente Técnico ───────────────────────────────────────
    if button_id == BotonesMenu.INCIDENTE:
        await update_chat_context(numero_huesped, ContextoChat.AWAITING_TICKET)
        await whatsapp_service.enviar_solicitud_ticket(
            phone_number_id = phone_number_id,
            to              = numero_huesped,
            idioma          = idioma,
        )
        return

    # ── ❓ Otra Consulta (activa la IA) ──────────────────────────────────────
    if button_id == BotonesMenu.CONSULTA:
        await _flujo_ia_general(
            numero_huesped  = numero_huesped,
            texto_mensaje   = "Tengo una consulta general sobre el hotel.",
            phone_number_id = phone_number_id,
        )
        return


async def _manejar_ticket(
    numero_huesped:  str,
    phone_number_id: str,
    texto_mensaje:   str,
    idioma:          str,
    habitacion:      str,
) -> None:
    """Clasifica el ticket, alerta si es emergencia o lo guarda si es normal.

    Flujo:
        1. clasificar_ticket() → (es_emergencia, resumen)
        2. Si EMERGENCIA:
           - Enviar aviso de emergencia al huésped
           - logging.warning "DISPARAR ALERTA TWILIO/TELEGRAM"
           - registrar_ticket con tipo=EMERGENCIA
        3. Si NORMAL:
           - registrar_ticket en pestaña Tickets_Soporte
           - Enviar confirmación al huésped
           - Resetear contexto a NORMAL
    """
    import asyncio

    hotel_context = await get_hotel_rules()
    es_emerg, resumen = await clasificar_ticket(texto_mensaje, hotel_context)

    if es_emerg:
        logger.warning(
            "DISPARAR ALERTA TWILIO/TELEGRAM | "
            "TICKET EMERGENCIA | huesped=%s | hab=%s | resumen=%r | detalle=%r",
            numero_huesped, habitacion, resumen, texto_mensaje[:100],
        )
        # TODO producción: llamar al servicio de alertas con datos del ticket
        # await alerta_service.notificar_emergencia(
        #     numero_huesped=numero_huesped,
        #     habitacion=habitacion,
        #     detalle=texto_mensaje,
        # )

        # Enviar instrucciones de calma al huésped Y registrar el ticket
        await asyncio.gather(
            whatsapp_service.enviar_aviso_emergencia(
                phone_number_id = phone_number_id,
                to              = numero_huesped,
                idioma          = idioma,
            ),
            registrar_ticket(
                numero_huesped = numero_huesped,
                habitacion     = habitacion,
                detalle        = texto_mensaje,
                tipo           = "EMERGENCIA",
            ),
            # Resetear contexto aunque sea emergencia
            update_chat_context(numero_huesped, ContextoChat.NORMAL),
        )
        return

    # ── Ticket normal: guardar + confirmar + resetear ─────────────────────────
    await asyncio.gather(
        registrar_ticket(
            numero_huesped = numero_huesped,
            habitacion     = habitacion,
            detalle        = texto_mensaje,
            tipo           = "NORMAL",
        ),
        update_chat_context(numero_huesped, ContextoChat.NORMAL),
    )
    logger.info(
        "Ticket NORMAL registrado | hab=%s | resumen=%r",
        habitacion, resumen,
    )
    await whatsapp_service.enviar_confirmacion_ticket(
        phone_number_id = phone_number_id,
        to              = numero_huesped,
        idioma          = idioma,
    )


async def _flujo_ia_general(
    numero_huesped:  str,
    texto_mensaje:   str,
    phone_number_id: str,
) -> None:
    """Genera y envía una respuesta con Gemini Flash usando el PDF del hotel.

    Detecta emergencias y dispara la alerta correspondiente si la respuesta
    comienza con el tag [EMERGENCIA].
    """
    hotel_id = settings.crm_hotel_id

    hotel_context = await get_hotel_rules()
    if not hotel_context:
        hotel_context = (
            "No hay información específica del hotel disponible. "
            "Responde de forma genérica y profesional."
        )

    respuesta_ia = await generate_response(
        guest_message = texto_mensaje,
        hotel_context = hotel_context,
    )

    if es_emergencia(respuesta_ia):
        logger.warning(
            "DISPARAR ALERTA TWILIO/TELEGRAM | "
            "hotel=%r | huesped=%s | respuesta=%r",
            hotel_id, numero_huesped, respuesta_ia[:120],
        )
    elif detectar_emergencia_en_mensaje(texto_mensaje) and not es_emergencia(respuesta_ia):
        logger.warning(
            "Pipeline: posible emergencia NO detectada por IA | msg=%r",
            texto_mensaje[:80],
        )

    await _enviar_respuesta(phone_number_id, numero_huesped, respuesta_ia)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de la Graph API de Meta
# ─────────────────────────────────────────────────────────────────────────────


async def _enviar_respuesta(
    phone_number_id: str,
    to:              str,
    texto:           str,
) -> None:
    """Envía un mensaje de texto al huésped a través de la WhatsApp Cloud API.

    Usa ``httpx.AsyncClient`` con POST asíncrono hacia los servidores de Meta.
    La URL incluye el ``phone_number_id`` del número receptor del hotel, lo que
    permite que un mismo servidor atienda múltiples números de hotel.

    Args:
        phone_number_id: ID del número de WhatsApp Business receptor (hotel).
        to:              Número del huésped destino (formato internacional).
        texto:           Texto de la respuesta a enviar.
    """
    if not _wa_client:
        logger.error("WhatsApp: cliente HTTP no inicializado — no se puede enviar.")
        return

    # Construir URL dinámica con el phone_number_id extraído del payload
    # (permite multi-hotel en la misma instancia del servidor)
    url = (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        f"/{phone_number_id}/messages"
    )

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                to,
        "type":              "text",
        "text": {
            "preview_url": False,
            "body":        texto,
        },
    }

    try:
        response = await _wa_client.post(url, json=payload)

        if response.is_success:
            logger.info(
                "WhatsApp: respuesta enviada | to=%s | chars=%d | HTTP=%s",
                to, len(texto), response.status_code,
            )
        else:
            logger.error(
                "WhatsApp: error al enviar | HTTP %s | to=%s | body=%s",
                response.status_code, to, response.text[:200],
            )

    except httpx.TimeoutException:
        logger.error("WhatsApp: timeout enviando respuesta a %s.", to)
    except Exception as exc:
        logger.error(
            "WhatsApp: excepción enviando respuesta a %s | %s: %s",
            to, type(exc).__name__, exc,
        )


async def _marcar_leido(phone_number_id: str, message_id: str) -> None:
    """Envía el doble check azul al huésped (marca el mensaje como leído).

    Meta lo usa para mostrar que el servidor recibió y procesó el mensaje.
    Fallo silencioso: si no funciona, solo se registra en el log.
    """
    if not _wa_client or not message_id or not phone_number_id:
        return

    url = (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        f"/{phone_number_id}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "status":            "read",
        "message_id":        message_id,
    }
    try:
        await _wa_client.post(url, json=payload)
    except Exception as exc:
        logger.debug("WhatsApp: no se pudo marcar como leído | %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de parsing del payload
# ─────────────────────────────────────────────────────────────────────────────


def _extraer_datos_mensaje(
    payload: WaPayload,
) -> tuple[str, str, str, str, str] | None:
    """Extrae los datos relevantes del primer mensaje del payload.

    Soporta mensajes de texto y mensajes interactivos (respuesta a botones
    o selección de lista).

    Returns:
        ``(numero_wa, texto, phone_number_id, message_id, button_id)``
        - ``texto``     es el body del mensaje si es texto, "" si es interactivo.
        - ``button_id`` es el ID del botón si es interactivo, "" si es texto.
        Retorna ``None`` si no hay mensaje procesable (imagen, audio, status, etc.).
    """
    try:
        entry   = payload.entry[0]
        change  = entry.changes[0]
        value   = change.value

        if not value.messages:
            return None

        mensaje = value.messages[0]
        numero  = mensaje.from_
        phone_number_id = (
            value.metadata.phone_number_id
            if value.metadata
            else settings.whatsapp_phone_number_id
        )

        # ── Mensaje de texto normal ───────────────────────────────────────────
        if mensaje.type == "text" and mensaje.text is not None:
            return numero, mensaje.text.body, phone_number_id, mensaje.id, ""

        # ── Respuesta interactiva (selección de lista o botón) ────────────────
        if mensaje.es_interactivo and mensaje.button_id:
            return numero, "", phone_number_id, mensaje.id, mensaje.button_id

        logger.debug("WhatsApp: tipo de mensaje ignorado: %r.", mensaje.type)
        return None

    except (IndexError, AttributeError) as exc:
        logger.debug("WhatsApp: no se pudo extraer mensaje | %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Detección de intenciones — Check-out y Late Check-out (Escenario 4)
# ─────────────────────────────────────────────────────────────────────────────

_KEYWORDS_CHECKOUT: dict[str, frozenset[str]] = {
    "es": frozenset({
        "checkout", "check-out", "check out", "hacer checkout",
        "irme", "me voy", "ya me voy", "me tengo que ir",
        "dejar la habitación", "dejar la habitacion", "dejar el cuarto",
        "hora de salida", "salida", "salir del hotel", "salir de la habitación",
        "hora de irme", "me estoy yendo", "salgo hoy", "salida hoy",
        "entregar llave", "entregar la llave", "dejar llave",
    }),
    "en": frozenset({
        "checkout", "check out", "check-out", "checking out",
        "leaving", "i'm leaving", "im leaving", "leaving now",
        "leaving the room", "departure", "time to leave",
        "drop off key", "return key", "hand in key",
        "what do i do when i leave", "how do i check out",
    }),
    "pt": frozenset({
        "checkout", "check-out", "check out", "fazer checkout",
        "ir embora", "me vou", "vou sair", "saindo",
        "deixar o quarto", "saída do hotel", "hora de sair",
        "entregar chave", "deixar a chave",
    }),
}

_KEYWORDS_LATE_CHECKOUT: dict[str, frozenset[str]] = {
    "es": frozenset({
        "late checkout", "late check-out", "salida tardía",
        "quedarme hasta", "quedarme más", "quedarme mas",
        "puedo quedarme", "puedo quedar", "puede quedarme",
        "salir más tarde", "salir mas tarde", "hasta las 2", "hasta las 3",
        "tarde para salir", "más tiempo", "mas tiempo en la habitacion",
        "extender estadía", "extender estadia", "extender mi estadía",
        "extender mi estadia", "necesito más tiempo", "no puedo salir a las",
    }),
    "en": frozenset({
        "late checkout", "late check-out",
        "stay longer", "leave later", "check out later",
        "can i stay", "is it possible to stay", "extend my stay",
        "past checkout time", "after checkout", "after check-out",
        "a bit later", "few more hours", "until 2", "until 3",
    }),
    "pt": frozenset({
        "late checkout", "late check-out", "saída tardia",
        "ficar até", "posso ficar", "sair mais tarde",
        "estender estadia", "mais horas", "tarde para sair",
        "depois do horário", "precisar de mais tempo",
    }),
}

# Palabras de afirmación/negación para la confirmación de late checkout
_KEYWORDS_AFIRMACION: frozenset[str] = frozenset({
    "si", "sí", "yes", "sim", "quiero", "quero", "ok", "okay",
    "dale", "claro", "confirmo", "acepto", "adelante", "perfecto",
    "sure", "go ahead", "please", "absolutely", "definitively",
    "puede ser", "certo", "com certeza", "por favor",
})
_KEYWORDS_NEGACION: frozenset[str] = frozenset({
    "no", "nao", "não", "cancel", "cancelar", "no gracias", "no quiero",
    "no quero", "nope", "negative", "cancela",
})


def detectar_intencion_checkout(texto: str, idioma: str = "es") -> bool:
    """True si el mensaje indica que el huésped quiere hacer el check-out."""
    texto_lower = texto.lower()
    orden = [idioma] + [k for k in _KEYWORDS_CHECKOUT if k != idioma]
    return any(
        kw in texto_lower
        for lang in orden
        for kw in _KEYWORDS_CHECKOUT.get(lang, frozenset())
    )


def detectar_intencion_late_checkout(texto: str, idioma: str = "es") -> bool:
    """True si el mensaje indica que el huésped quiere solicitar late check-out."""
    texto_lower = texto.lower()
    orden = [idioma] + [k for k in _KEYWORDS_LATE_CHECKOUT if k != idioma]
    return any(
        kw in texto_lower
        for lang in orden
        for kw in _KEYWORDS_LATE_CHECKOUT.get(lang, frozenset())
    )


def detectar_afirmacion(texto: str) -> bool:
    """True si el mensaje es una respuesta afirmativa (sí/yes/sim)."""
    texto_lower = texto.lower().strip()
    return any(kw in texto_lower for kw in _KEYWORDS_AFIRMACION)


def detectar_negacion(texto: str) -> bool:
    """True si el mensaje es una respuesta negativa (no/cancel)."""
    texto_lower = texto.lower().strip()
    return any(kw in texto_lower for kw in _KEYWORDS_NEGACION)


# ─────────────────────────────────────────────────────────────────────────────
# Detección de intención de llegada (Escenario 2)
# ─────────────────────────────────────────────────────────────────────────────

# Keywords que indican que el huésped ya llegó o quiere acceder a su habitación.
# Ordenados por idioma para minimizar iteración en el caso común (español).
_KEYWORDS_LLEGADA: dict[str, frozenset[str]] = {
    "es": frozenset({
        "ya llegue", "ya llegué", "acabo de llegar", "estoy llegando",
        "llegue", "llegué", "ya estoy", "estoy aqui", "estoy aquí",
        "como entro", "cómo entro", "como se entra", "cómo se entra",
        "codigo de puerta", "código de puerta", "pin acceso", "pin de acceso",
        "clave de entrada", "clave acceso", "como abro", "cómo abro",
        "estoy en la puerta", "estoy afuera", "abrir puerta", "acceso habitacion",
        "instrucciones de entrada", "como llego", "cómo llego",
        "donde es", "dónde es", "como llegar", "cómo llegar",
    }),
    "en": frozenset({
        "just arrived", "i arrived", "i'm here", "im here", "already here",
        "i'm at the hotel", "im at the hotel", "how do i enter", "how to enter",
        "door code", "access code", "pin code", "room access", "entry code",
        "how to get in", "at the door", "outside now", "arrival",
        "how to open", "open the door", "check in", "checking in",
        "where is the entrance", "directions", "how to arrive",
    }),
    "pt": frozenset({
        "acabei de chegar", "ja cheguei", "já cheguei", "estou chegando",
        "como entro", "codigo da porta", "código da porta", "pin de acesso",
        "como abro", "como se entra", "instrucoes de chegada",
        "instruções de chegada", "estou na porta", "como acesso",
        "onde fica", "como chegar", "acabei de chegar", "estou aqui",
        "check-in", "fazer check in",
    }),
}


def detectar_intencion_llegada(texto: str, idioma: str = "es") -> bool:
    """Detecta si el mensaje indica que el huésped está llegando al hotel.

    Busca palabras clave en el idioma configurado del huésped primero,
    luego en los demás idiomas como fallback (cubre casos de huéspedes
    que mezclan idiomas).

    Args:
        texto:  Mensaje del huésped (se normaliza a minúsculas).
        idioma: Código de idioma preferido (es|en|pt).

    Returns:
        True si el texto contiene intención de llegada.
    """
    texto_lower = texto.lower()

    # Buscar primero en el idioma del huésped, luego en los otros
    orden_busqueda = [idioma] + [k for k in _KEYWORDS_LLEGADA if k != idioma]

    for lang in orden_busqueda:
        keywords = _KEYWORDS_LLEGADA.get(lang, frozenset())
        if any(kw in texto_lower for kw in keywords):
            return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# Constructores de mensajes multilingüe
# ─────────────────────────────────────────────────────────────────────────────

# Confirmación cuando el bot ya está esperando el DNI y el huésped escribe algo
_MSG_DNI_RECIBIDO: dict[str, str] = {
    "es": (
        "Gracias por tu mensaje. 📋\n\n"
        "Cuando hayas completado el formulario de registro, tu acceso quedará "
        "habilitado automáticamente. Si tenés alguna duda, respondé aquí."
    ),
    "en": (
        "Thank you for your message. 📋\n\n"
        "Once you complete the registration form, your access will be enabled "
        "automatically. If you have any questions, reply here."
    ),
    "pt": (
        "Obrigado pela sua mensagem. 📋\n\n"
        "Quando você concluir o formulário de registro, seu acesso será "
        "habilitado automaticamente. Se tiver dúvidas, responda aqui."
    ),
}


def _construir_mensaje_precheckin(nombre: str, idioma: str, form_url: str) -> str:
    """Construye el mensaje de solicitud de pre-check-in en el idioma del huésped.

    El mensaje interrumpe cualquier otra conversación — es el primer paso
    obligatorio antes de poder usar el sistema de acceso nocturno.

    Args:
        nombre:   Nombre del huésped (para personalizar el saludo).
        idioma:   Código de idioma (es|en|pt).
        form_url: URL del formulario Django donde sube su DNI/Pasaporte.
    """
    saludo = f"{nombre}," if nombre else ""

    plantillas: dict[str, str] = {
        "es": (
            f"¡Hola{' ' + saludo if saludo else ''}! 👋\n\n"
            "Para habilitar tus códigos de acceso nocturno y completar tu "
            "registro legal, necesitamos que subas tu DNI o Pasaporte.\n\n"
            f"✅ *Completa tu registro aquí:*\n{form_url}\n\n"
            "Solo te tomará 2 minutos y tus accesos quedarán habilitados "
            "automáticamente. ¡Gracias!"
        ),
        "en": (
            f"Hello{' ' + saludo if saludo else ''}! 👋\n\n"
            "To enable your nighttime access codes and complete your legal "
            "registration, please upload your ID or Passport.\n\n"
            f"✅ *Complete your registration here:*\n{form_url}\n\n"
            "It only takes 2 minutes and your access will be enabled "
            "automatically. Thank you!"
        ),
        "pt": (
            f"Olá{' ' + saludo if saludo else ''}! 👋\n\n"
            "Para habilitar seus códigos de acesso noturno e concluir seu "
            "registro legal, precisamos que você envie seu RG ou Passaporte.\n\n"
            f"✅ *Conclua seu registro aqui:*\n{form_url}\n\n"
            "Leva apenas 2 minutos e seus acessos serão habilitados "
            "automaticamente. Obrigado!"
        ),
    }
    return plantillas.get(idioma, plantillas["es"])


def _construir_mensaje_checkin(
    nombre:     str,
    habitacion: str,
    pin:        str,
    carpeta_id: str,
    idioma:     str,
) -> str:
    """Construye el mensaje de bienvenida de Check-In con todos los datos de acceso.

    Incluye:
    - Saludo personalizado con el nombre del huésped
    - Número de habitación
    - PIN de la cerradura/puerta
    - Link a la carpeta de Google Drive con el mapa, fotos y/o video de llegada

    Args:
        nombre:     Nombre del huésped.
        habitacion: Número/nombre de la habitación (col D).
        pin:        Código PIN de acceso (col L).
        carpeta_id: ID de la carpeta Drive (col H) → se convierte a URL.
        idioma:     Código de idioma (es|en|pt).
    """
    drive_url = (
        f"https://drive.google.com/drive/folders/{carpeta_id}"
        if carpeta_id else ""
    )
    pin_display  = pin        if pin        else "—"
    hab_display  = habitacion if habitacion else "—"
    saludo       = f"{nombre}" if nombre else "Estimado/a huésped"

    plantillas: dict[str, str] = {
        "es": (
            f"¡Bienvenido/a, {saludo}! 🏨🎉\n\n"
            "Aquí está toda la información para acceder a tu habitación:\n\n"
            f"🚪 *Habitación:* {hab_display}\n"
            f"🔑 *PIN de acceso:* {pin_display}\n\n"
            + (
                f"📍 *Mapa de llegada e instrucciones:*\n{drive_url}\n\n"
                if drive_url else ""
            )
            + "¡Que disfrutes tu estadía! Estoy disponible toda la noche "
            "si necesitás algo. 🌙"
        ),
        "en": (
            f"Welcome, {saludo}! 🏨🎉\n\n"
            "Here's all the information to access your room:\n\n"
            f"🚪 *Room:* {hab_display}\n"
            f"🔑 *Access PIN:* {pin_display}\n\n"
            + (
                f"📍 *Arrival map & instructions:*\n{drive_url}\n\n"
                if drive_url else ""
            )
            + "Enjoy your stay! I'm available all night if you need anything. 🌙"
        ),
        "pt": (
            f"Bem-vindo/a, {saludo}! 🏨🎉\n\n"
            "Aqui estão todas as informações para acessar seu quarto:\n\n"
            f"🚪 *Quarto:* {hab_display}\n"
            f"🔑 *PIN de acesso:* {pin_display}\n\n"
            + (
                f"📍 *Mapa de chegada e instruções:*\n{drive_url}\n\n"
                if drive_url else ""
            )
            + "Aproveite sua estadia! Estou disponível a noite toda se precisar "
            "de algo. 🌙"
        ),
    }
    return plantillas.get(idioma, plantillas["es"])


def _validar_firma_meta(body: bytes, signature_header: str) -> None:
    """Valida la firma HMAC-SHA256 de Meta en el header X-Hub-Signature-256.

    Meta firma el cuerpo del webhook con el ``APP_SECRET`` de la aplicación.
    Actualmente usa el ``whatsapp_access_token`` como secreto (suficiente para MVP).
    En producción, configurar ``META_APP_SECRET`` en .env y reemplazarlo aquí.

    Raises:
        HTTPException 400: Formato de firma inválido.
        HTTPException 403: Firma HMAC no coincide (posible payload falsificado).
    """
    if not signature_header.startswith("sha256="):
        raise HTTPException(status_code=400, detail="Formato de firma inválido")

    firma_recibida = signature_header.removeprefix("sha256=")
    firma_esperada = hmac.new(
        settings.whatsapp_access_token.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(firma_recibida, firma_esperada):
        logger.warning("WhatsApp: firma HMAC-SHA256 inválida — payload posiblemente falsificado.")
        raise HTTPException(status_code=403, detail="Firma inválida")
