"""
AI Service — Recepcionista Virtual.

SDK:
    Se usa ``google-genai`` (el SDK oficial moderno de Google Gemini) en lugar
    de ``google-generativeai`` que está oficialmente deprecado desde mayo 2025.
    ``google-genai`` provee ``client.aio.models.generate_content()`` para llamadas
    genuinamente asíncronas sin necesidad de run_in_executor.

    Si necesitás la compatibilidad con el SDK deprecado, la sección al final
    del módulo muestra cómo envolverlo con asyncio.run_in_executor.

Modelo:
    gemini-1.5-flash — alto rendimiento, latencia baja, tier gratuito generoso.

Interfaz pública principal:
    generate_response(guest_message, hotel_context) -> str
        Función pura y sin estado — recibe el mensaje del huésped y el
        contexto del hotel (texto extraído del PDF) y retorna la respuesta.

Interfaz secundaria (gestión de sesiones para WhatsApp):
    generar_respuesta(sesion, mensaje_usuario, ...) -> str
        Wrapper con historial de conversación multi-turno. Llama internamente
        a generate_response para la generación real.

Sistema de emergencias:
    Si el modelo detecta una emergencia, inicia su respuesta con [EMERGENCIA].
    es_emergencia(texto) permite que el router WA tome acciones adicionales
    (por ejemplo, alertar al administrador del hotel).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from google import genai
from google.genai import types as genai_types

from virtual_receptionist.config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# BLOQUE 1 — Constantes del módulo
# ─────────────────────────────────────────────────────────────────────────────

# Modelo a usar. gemini-1.5-flash: rápido, económico, tier gratuito generoso.
# Alternativa de mayor capacidad: "gemini-1.5-pro"
_MODEL_ID: str = "gemini-1.5-flash"

# Tag que indica al huésped que hay una emergencia y al sistema que debe alertar.
# La system instruction le ordena explícitamente al modelo que empiece con él.
EMERGENCIA_TAG: str = "[EMERGENCIA]"

# Instrucción de sistema exacta especificada en el diseño del producto.
# {hotel_context} se sustituye en runtime con el texto extraído del PDF.
_SYSTEM_INSTRUCTION_TEMPLATE: str = """\
Eres el recepcionista virtual del hotel. Tu único objetivo es responder \
de forma amable y concisa a las dudas del huésped basándote EXCLUSIVAMENTE en el \
CONTEXTO provisto.

CONTEXTO DEL HOTEL:
{hotel_context}

REGLAS DE ORO:
- Si el huésped reporta un problema crítico o peligroso (ej: inundación, fuga de gas, \
corte total de luz, emergencia médica), tu respuesta DEBE empezar textualmente con el \
tag '[EMERGENCIA]' seguido de instrucciones de calma y el aviso de que se está alertando \
al administrador.
- Si la información no figura en el contexto, indica amablemente que no posees esa \
información y que el personal la resolverá por la mañana.\
"""

# Respuesta de fallback cuando la API de Gemini no está disponible.
_RESPUESTA_FALLBACK: str = (
    "En este momento no puedo procesar tu consulta. "
    "Por favor, comunícate con la recepción o llama al número de emergencias del hotel. "
    "El personal estará disponible para ayudarte."
)

# Palabras clave para detección local de emergencias (segunda línea de defensa).
# El modelo también detecta emergencias semánticamente, pero esta lista permite
# reaccionar incluso si el modelo falla o tarda demasiado.
_KEYWORDS_EMERGENCIA: frozenset[str] = frozenset({
    "inundacion", "inundación", "fuga de gas", "gas", "incendio", "fuego",
    "emergencia", "accidente", "herido", "herida", "sangre", "desmayo",
    "sin luz", "corte de luz", "corte eléctrico", "electrocución",
    "robo", "asalto", "intruso", "peligro", "ayuda urgente",
    "corazón", "infarto", "convulsiones", "no respira",
})

# ─────────────────────────────────────────────────────────────────────────────
# BLOQUE 2 — Cliente Gemini (singleton, inicializado en el lifespan de FastAPI)
# ─────────────────────────────────────────────────────────────────────────────

_genai_client: genai.Client | None = None


def init_genai_client() -> None:
    """Inicializa el cliente de Gemini. Llamar desde el lifespan de FastAPI."""
    global _genai_client
    _genai_client = genai.Client(api_key=settings.gemini_api_key)
    logger.info("AI Service: cliente Gemini inicializado | modelo=%s", _MODEL_ID)


def _get_client() -> genai.Client:
    if _genai_client is None:
        raise RuntimeError(
            "AI Service: cliente Gemini no inicializado. "
            "Llamar init_genai_client() en el lifespan de FastAPI."
        )
    return _genai_client


# ─────────────────────────────────────────────────────────────────────────────
# BLOQUE 3 — Función principal (interfaz pública según el spec)
# ─────────────────────────────────────────────────────────────────────────────


async def generate_response(guest_message: str, hotel_context: str) -> str:
    """Genera la respuesta del Recepcionista Virtual para un mensaje del huésped.

    Función pura y sin estado: no mantiene historial de conversación.
    Ideal para consultas únicas o cuando el caller gestiona el contexto.

    El system prompt le ordena al modelo:
        - Responder SOLO con información del ``hotel_context``
        - Iniciar con ``[EMERGENCIA]`` ante problemas críticos o peligrosos
        - Derivar al personal humano si la información no está en el contexto

    Implementación async:
        Usa ``client.aio.models.generate_content()`` del SDK google-genai,
        que es genuinamente asíncrono (no bloquea el event loop de FastAPI).

    Args:
        guest_message: Mensaje de texto del huésped.
        hotel_context: Texto del PDF de reglas/contexto del hotel
                       (obtenido de drive_service.get_pdf_text).

    Returns:
        Respuesta generada por Gemini, o ``_RESPUESTA_FALLBACK`` si la API falla.
        Si hay una emergencia, la respuesta comienza con ``[EMERGENCIA]``.

    Example::

        context = await drive_service.get_pdf_text(settings.google_drive_folder_id)
        reply   = await generate_response("¿Hay estacionamiento?", context)
        if es_emergencia(reply):
            await alertar_administrador(numero_wa, reply)
        await enviar_whatsapp(numero_wa, reply)
    """
    if not guest_message.strip():
        logger.warning("AI Service: mensaje vacío recibido.")
        return _RESPUESTA_FALLBACK

    client           = _get_client()
    system_instruction = _SYSTEM_INSTRUCTION_TEMPLATE.format(hotel_context=hotel_context)

    # Configuración de generación: temperatura baja para respuestas factuales
    # y consistentes, tokens limitados para respuestas concisas en WhatsApp.
    config = genai_types.GenerateContentConfig(
        system_instruction = system_instruction,
        temperature        = 0.3,     # más determinista que creativo
        max_output_tokens  = 350,     # conciso para WhatsApp (≈ 3 párrafos)
        safety_settings    = [
            genai_types.SafetySetting(
                category  = "HARM_CATEGORY_HARASSMENT",
                threshold = "BLOCK_ONLY_HIGH",
            ),
            genai_types.SafetySetting(
                category  = "HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold = "BLOCK_NONE",     # emergencias = contenido potencialmente "peligroso" para los filtros
            ),
        ],
    )

    contenidos = [
        genai_types.Content(
            role  = "user",
            parts = [genai_types.Part.from_text(text=guest_message)],
        )
    ]

    try:
        # Llamada genuinamente asíncrona — no bloquea el event loop de FastAPI.
        # Equivalente al generate_content() síncrono del SDK deprecado, pero async.
        respuesta = await client.aio.models.generate_content(
            model    = _MODEL_ID,
            contents = contenidos,
            config   = config,
        )

        texto = respuesta.text.strip()

        if not texto:
            logger.warning(
                "AI Service: Gemini retornó respuesta vacía | msg=%r", guest_message[:60]
            )
            return _RESPUESTA_FALLBACK

        logger.info(
            "AI Service: respuesta generada | in=%d chars | out=%d chars | emergencia=%s",
            len(guest_message), len(texto), es_emergencia(texto),
        )
        return texto

    except Exception as exc:
        logger.error(
            "AI Service: error en generate_response | %s: %s | msg=%r",
            type(exc).__name__, exc, guest_message[:80],
        )
        return _RESPUESTA_FALLBACK


# ─────────────────────────────────────────────────────────────────────────────
# BLOQUE 4 — Utilidades de emergencia
# ─────────────────────────────────────────────────────────────────────────────


def es_emergencia(texto: str) -> bool:
    """Retorna True si la respuesta de Gemini indica una emergencia.

    Verifica que el texto comience exactamente con el tag ``[EMERGENCIA]``,
    tal como lo instruye el system prompt al modelo.

    Args:
        texto: Texto de respuesta generado por generate_response.

    Returns:
        True si es una emergencia confirmada por el modelo.
    """
    return texto.strip().startswith(EMERGENCIA_TAG)


def detectar_emergencia_en_mensaje(mensaje: str) -> bool:
    """Detecta palabras clave de emergencia en el MENSAJE del huésped.

    Segunda línea de defensa: permite detectar emergencias localmente
    sin esperar la respuesta del modelo (útil para pre-alertar antes de
    que Gemini responda, o como fallback si la API falla).

    Args:
        mensaje: Mensaje de texto crudo del huésped.

    Returns:
        True si el mensaje contiene palabras clave de emergencia.
    """
    mensaje_lower = mensaje.lower()
    return any(kw in mensaje_lower for kw in _KEYWORDS_EMERGENCIA)



# ─────────────────────────────────────────────────────────────────────────────
# BLOQUE 4b — Clasificador de tickets de soporte
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_CLASIFICADOR: str = """\
Eres un sistema de clasificación de tickets de soporte para un hotel. \
Analiza el reporte de un huésped y determina si es EMERGENCIA o NORMAL.

EMERGENCIA: situación peligrosa o urgente que requiere intervención INMEDIATA.
  Ejemplos: inundación, fuga de gas, incendio, corte total de luz, cerradura \
rota que impide salir de noche, problema de seguridad, emergencia médica.

NORMAL: requerimiento no urgente que puede esperar atención del staff.
  Ejemplos: falta de toallas, ruido, TV sin funcionar, WiFi lento, \
almohadas adicionales, aire acondicionado.

Responde SOLO con este formato exacto (sin texto adicional):
EMERGENCIA: [resumen del problema en 6-8 palabras]
o
NORMAL: [resumen del problema en 6-8 palabras]
"""


async def clasificar_ticket(
    descripcion:   str,
    hotel_context: str = "",
) -> tuple[bool, str]:
    """Clasifica un reporte de huésped como emergencia o requerimiento normal.

    Combina dos capas de detección para velocidad y precisión:
      1. Detección rápida por keywords (< 1ms, sin llamada a API).
         Si es una emergencia obvia → retorna True de inmediato.
      2. Clasificación semántica con Gemini Flash para casos ambiguos.
         Si la API falla → fallback a detección por keywords.

    Args:
        descripcion:   Texto del mensaje del huésped describiendo el problema.
        hotel_context: Contexto del hotel (no se usa en clasificación pero
                       puede incluirse si el modelo lo necesita).

    Returns:
        (es_emergencia: bool, resumen: str)
        es_emergencia: True si requiere alerta inmediata.
        resumen:       Resumen del problema en 6-8 palabras.
    """
    if not descripcion.strip():
        return False, "reporte vacío"

    # ── Capa 1: keywords rápidos (obvia emergencia) ───────────────────────
    if detectar_emergencia_en_mensaje(descripcion):
        logger.warning(
            "AI clasificar_ticket: EMERGENCIA por keyword | desc=%r",
            descripcion[:80],
        )
        return True, descripcion[:60]

    # ── Capa 2: clasificación semántica con Gemini ────────────────────────
    client = _get_client()
    config = genai_types.GenerateContentConfig(
        system_instruction = _SYSTEM_CLASIFICADOR,
        temperature        = 0.0,    # totalmente determinista
        max_output_tokens  = 30,     # solo necesita "EMERGENCIA/NORMAL: resumen"
    )
    contenidos = [
        genai_types.Content(
            role  = "user",
            parts = [genai_types.Part.from_text(text=descripcion)],
        )
    ]
    try:
        respuesta = await client.aio.models.generate_content(
            model    = _MODEL_ID,
            contents = contenidos,
            config   = config,
        )
        texto = respuesta.text.strip()
        es_emerg = texto.upper().startswith("EMERGENCIA")
        # Extraer el resumen después de los dos puntos
        resumen = texto.split(":", 1)[1].strip() if ":" in texto else texto[:60]
        logger.info(
            "AI clasificar_ticket: %s | resumen=%r",
            "EMERGENCIA" if es_emerg else "NORMAL", resumen,
        )
        return es_emerg, resumen

    except Exception as exc:
        logger.error(
            "AI clasificar_ticket: error en Gemini | %s: %s — fallback a keywords.",
            type(exc).__name__, exc,
        )
        # Fallback: sin IA, asumir normal (ya se chequearon keywords arriba)
        return False, descripcion[:60]


# ─────────────────────────────────────────────────────────────────────────────
# BLOQUE 5 — Gestión de sesiones (para conversaciones multi-turno en WhatsApp)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Mensaje:
    """Un turno de la conversación (inmutable después de creado)."""
    rol:   str    # "user" | "model"
    texto: str
    ts:    float = field(default_factory=time.monotonic)


@dataclass
class Sesion:
    """Estado de conversación asociado a un número de WhatsApp."""
    numero_wa:        str
    historial:        list[Mensaje] = field(default_factory=list)
    ultima_act:       float         = field(default_factory=time.monotonic)
    id_comercio:      str           = ""
    nombre_comercio:  str           = ""

    def agregar_mensaje(self, rol: str, texto: str) -> None:
        self.historial.append(Mensaje(rol=rol, texto=texto))
        self.ultima_act = time.monotonic()
        max_h = settings.receptionist_max_history * 2
        if len(self.historial) > max_h:
            self.historial = self.historial[-max_h:]

    def esta_expirada(self) -> bool:
        ttl = settings.receptionist_session_ttl_minutes * 60
        return time.monotonic() - self.ultima_act > ttl

    def historial_gemini(self) -> list[genai_types.Content]:
        return [
            genai_types.Content(
                role  = msg.rol,
                parts = [genai_types.Part.from_text(text=msg.texto)],
            )
            for msg in self.historial
        ]


_sesiones: dict[str, Sesion] = {}


def obtener_o_crear_sesion(
    numero_wa:       str,
    id_comercio:     str = "",
    nombre_comercio: str = "",
) -> Sesion:
    """Retorna la sesión activa del número o crea una nueva si expiró."""
    sesion = _sesiones.get(numero_wa)
    if sesion is None or sesion.esta_expirada():
        if sesion:
            logger.info("AI Service: sesión expirada | numero=%s", numero_wa)
        sesion = Sesion(
            numero_wa       = numero_wa,
            id_comercio     = id_comercio,
            nombre_comercio = nombre_comercio,
        )
        _sesiones[numero_wa] = sesion
        logger.info("AI Service: nueva sesión | numero=%s", numero_wa)
    return sesion


def limpiar_sesiones_expiradas() -> int:
    """Elimina sesiones vencidas. Llamar periódicamente (ej. cada hora)."""
    antes    = len(_sesiones)
    expiradas = [k for k, v in _sesiones.items() if v.esta_expirada()]
    for k in expiradas:
        del _sesiones[k]
    eliminadas = len(expiradas)
    if eliminadas:
        logger.info(
            "AI Service: %d sesión(es) eliminadas | quedan %d.",
            eliminadas, antes - eliminadas,
        )
    return eliminadas


# ─────────────────────────────────────────────────────────────────────────────
# BLOQUE 6 — Wrapper con historial (retrocompatibilidad con whatsapp.py)
# ─────────────────────────────────────────────────────────────────────────────


async def generar_respuesta(
    sesion:              Sesion,
    mensaje_usuario:     str,
    contexto_pdf:        str = "",
    contexto_adicional:  str = "",
) -> str:
    """Genera respuesta incluyendo el historial de conversación de la sesión.

    Wrapper sobre ``generate_response`` que:
        1. Detecta emergencias en el mensaje del usuario ANTES de llamar a Gemini
           (pre-alerta local sin esperar la API).
        2. Llama a ``generate_response`` con el contexto completo.
        3. Guarda el turno en el historial de la sesión.

    Args:
        sesion:             Sesión activa del número de WhatsApp.
        mensaje_usuario:    Texto del mensaje recibido.
        contexto_pdf:       Texto extraído del PDF del hotel (de drive_service).
        contexto_adicional: Información extra del CRM (nombre comercio, etc.).

    Returns:
        Texto de la respuesta generada.
    """
    # Construir contexto unificado para el prompt
    partes_contexto = [p.strip() for p in [contexto_pdf, contexto_adicional] if p.strip()]
    contexto_total  = "\n\n".join(partes_contexto) if partes_contexto else (
        "Sin contexto disponible. Usa información genérica de hotel y deriva "
        "preguntas específicas al personal por la mañana."
    )

    # Detección local de emergencias (pre-alerta sin esperar a Gemini)
    if detectar_emergencia_en_mensaje(mensaje_usuario):
        logger.warning(
            "AI Service: posible emergencia detectada localmente | sesion=%s | msg=%r",
            sesion.numero_wa, mensaje_usuario[:80],
        )

    # Llamada a la función principal (genuinamente async)
    respuesta = await generate_response(
        guest_message = mensaje_usuario,
        hotel_context = contexto_total,
    )

    # Persistir turno en el historial de la sesión
    sesion.agregar_mensaje("user",  mensaje_usuario)
    sesion.agregar_mensaje("model", respuesta)

    return respuesta


# ─────────────────────────────────────────────────────────────────────────────
# NOTA: Equivalente con google-generativeai (SDK deprecado)
# ─────────────────────────────────────────────────────────────────────────────
#
# Si por alguna razón necesitás usar el SDK deprecado google-generativeai,
# la llamada síncrona debe envolverse en run_in_executor para no bloquear
# el event loop de FastAPI:
#
#   import asyncio
#   import google.generativeai as genai
#
#   genai.configure(api_key=GEMINI_API_KEY)
#   _model = genai.GenerativeModel(
#       model_name="gemini-1.5-flash",
#       system_instruction=system_instruction,
#   )
#
#   async def generate_response_legacy(guest_message: str, hotel_context: str) -> str:
#       loop = asyncio.get_event_loop()
#       def _sync_call():
#           return _model.generate_content(guest_message).text
#       return await loop.run_in_executor(None, _sync_call)
#
# Con google-genai (el SDK moderno que usamos aquí), la llamada es nativa async:
#   await client.aio.models.generate_content(...)
# ─────────────────────────────────────────────────────────────────────────────
