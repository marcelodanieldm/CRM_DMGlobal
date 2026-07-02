"""
CRM Service — Recepcionista Virtual Nocturno.

Responsabilidades:
    1. check_subscription(hotel_id)      → ¿tiene suscripción activa?
    2. obtener_contexto_comercio(id)     → nombre, tipo y estado del comercio
    3. obtener_config_feedback(uuid)     → review link y stats de feedback

Patrón de cliente:
    check_subscription usa httpx.AsyncClient() como context manager por llamada:
    simple, explícito y sin estado compartido — correcto para una función que
    se llama una vez por mensaje entrante de WhatsApp.

    Las funciones de contexto y feedback usan el cliente compartido inicializado
    en el lifespan de FastAPI para mayor eficiencia (connection pooling).

Variables de entorno requeridas (.env):
    CRM_DM_GLOBAL_API_URL   URL base del CRM Django (ej: https://crm.dmglobal.com)
    CRM_DM_GLOBAL_API_KEY   Clave de autenticación para los endpoints del CRM
    CRM_HOTEL_ID            ID del hotel/comercio (ej: HOTEL-TERRAZAS-01)
"""
from __future__ import annotations

import logging

import httpx

from virtual_receptionist.config import settings

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

# Estados del CRM que representan una suscripción válida y pagada.
_ESTADOS_ACTIVOS: frozenset[str] = frozenset({"active", "paid"})

# Timeouts diferenciados por fase de la conexión HTTP.
_TIMEOUT = httpx.Timeout(
    connect = 5.0,    # tiempo máximo para establecer la conexión TCP
    read    = 10.0,   # tiempo máximo para recibir la respuesta completa
    write   = 5.0,
    pool    = 5.0,
)

# ── Tipos de datos ────────────────────────────────────────────────────────────


class ComercioContexto:
    """Contexto mínimo del comercio usado para personalizar el system prompt."""

    __slots__ = ("id_comercio", "nombre", "tipo_negocio", "activo", "encontrado")

    def __init__(
        self,
        id_comercio: str  = "",
        nombre: str       = "",
        tipo_negocio: str = "",
        activo: bool      = False,
        encontrado: bool  = False,
    ) -> None:
        self.id_comercio  = id_comercio
        self.nombre       = nombre
        self.tipo_negocio = tipo_negocio
        self.activo       = activo
        self.encontrado   = encontrado

    def __repr__(self) -> str:
        return (
            f"<ComercioContexto id={self.id_comercio!r} "
            f"nombre={self.nombre!r} activo={self.activo}>"
        )


# ── 1. Verificación de suscripción ────────────────────────────────────────────


async def check_subscription(hotel_id: str) -> bool:
    """Verifica si el hotel tiene una suscripción activa en el CRM DM Global.

    Realiza un GET a ``{CRM_DM_GLOBAL_API_URL}/subscriptions/{hotel_id}``
    y evalúa el campo ``"status"`` de la respuesta JSON.

    Política de fallo abierto (fail-open):
        Si el CRM no responde —timeout, red caída, error 5xx— la función
        retorna ``True`` y loggea el error.  Esto garantiza que el huésped
        siempre reciba atención, incluso ante fallas de infraestructura.
        La única excepción es HTTP 404: si el hotel no existe en el CRM,
        retorna ``False`` (rechazo explícito y esperado).

    Args:
        hotel_id: Identificador del hotel en el CRM (ej: 'HOTEL-TERRAZAS-01').
                  Normalmente proviene de ``settings.crm_hotel_id``.

    Returns:
        ``True``  — suscripción activa ('active' o 'paid'), o CRM no disponible.
        ``False`` — suscripción inactiva/vencida/suspendida, o hotel no registrado.
    """
    url = f"{settings.crm_api_url}/subscriptions/{hotel_id}"

    # httpx.AsyncClient() como context manager: crea y cierra el cliente
    # en cada llamada. Simple, explícito, sin estado compartido.
    async with httpx.AsyncClient(
        timeout = _TIMEOUT,
        headers = {
            "Authorization": f"Bearer {settings.crm_api_key}",
            "X-API-Key":     settings.crm_api_key,
            "Accept":        "application/json",
        },
    ) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()

            data   = response.json()
            estado = str(data.get("status", "")).lower().strip()
            activo = estado in _ESTADOS_ACTIVOS

            logger.info(
                "check_subscription | hotel=%r | status=%r | autorizado=%s",
                hotel_id, estado, activo,
            )
            return activo

        # ── Timeout: red lenta o CRM sobrecargado ─────────────────────────
        except httpx.TimeoutException:
            logger.error(
                "check_subscription: TIMEOUT consultando hotel=%r en %s — "
                "retornando True (fail-open) para no dejar al huésped varado.",
                hotel_id, url,
            )
            return True

        # ── Error de conexión: CRM caído o DNS mal configurado ────────────
        except httpx.ConnectError:
            logger.error(
                "check_subscription: SIN CONEXIÓN al CRM para hotel=%r (%s) — "
                "retornando True (fail-open).",
                hotel_id, url,
            )
            return True

        # ── Errores HTTP explícitos ───────────────────────────────────────
        except httpx.HTTPStatusError as exc:
            codigo = exc.response.status_code

            if codigo == 404:
                # El hotel no existe en el CRM → rechazo explícito.
                logger.warning(
                    "check_subscription: hotel=%r no registrado en el CRM (404).",
                    hotel_id,
                )
                return False

            if codigo == 401 or codigo == 403:
                # API Key inválida o sin permisos → fallo de configuración.
                logger.error(
                    "check_subscription: sin autorización para hotel=%r "
                    "(HTTP %s) — verificar CRM_DM_GLOBAL_API_KEY en .env.",
                    hotel_id, codigo,
                )
                return True  # fail-open: problema de config, no de suscripción

            # 5xx u otros → fallo del servidor, política fail-open.
            logger.error(
                "check_subscription: HTTP %s para hotel=%r — "
                "retornando True (fail-open). Respuesta: %s",
                codigo, hotel_id, exc.response.text[:200],
            )
            return True

        # ── Cualquier otra excepción inesperada ───────────────────────────
        except Exception as exc:
            logger.error(
                "check_subscription: excepción inesperada para hotel=%r | "
                "%s: %s — retornando True (fail-open).",
                hotel_id, type(exc).__name__, exc,
            )
            return True


# ── 2. Contexto del comercio (cliente compartido) ─────────────────────────────

# Cliente HTTP compartido para las llamadas frecuentes al CRM.
# Se inicializa en el lifespan de FastAPI y se reutiliza entre peticiones.
_http_client: httpx.AsyncClient | None = None


async def init_http_client() -> None:
    """Inicializa el cliente HTTP compartido. Llamar desde el lifespan."""
    global _http_client
    _http_client = httpx.AsyncClient(
        base_url = settings.crm_api_url,
        timeout  = _TIMEOUT,
        headers  = {
            "Authorization": f"Bearer {settings.crm_api_key}",
            "X-API-Key":     settings.crm_api_key,
            "Accept":        "application/json",
        },
    )
    logger.info(
        "CRM Service: cliente compartido inicializado | base=%s", settings.crm_api_url
    )


async def close_http_client() -> None:
    """Cierra el cliente HTTP compartido. Llamar en el shutdown."""
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None
        logger.info("CRM Service: cliente compartido cerrado.")


def _client() -> httpx.AsyncClient:
    """Retorna el cliente compartido o lanza RuntimeError si no fue inicializado."""
    if _http_client is None:
        raise RuntimeError(
            "CRM Service: cliente no inicializado. "
            "Llamar init_http_client() en el lifespan de FastAPI."
        )
    return _http_client


async def obtener_contexto_comercio(id_comercio: str) -> ComercioContexto:
    """Consulta el CRM para obtener nombre, tipo y estado de un comercio.

    Llama a ``GET /api/v1/licencias/validar/?id_comercio=<id>``.
    Retorna un contexto vacío (``encontrado=False``) si la llamada falla,
    permitiendo que el Recepcionista opere en modo degradado.
    """
    try:
        response = await _client().get(
            "/api/v1/licencias/validar/",
            params={"id_comercio": id_comercio},
        )
        response.raise_for_status()
        data = response.json()

        return ComercioContexto(
            id_comercio  = id_comercio,
            nombre       = data.get("nombre_comercio", ""),
            tipo_negocio = data.get("tipo_negocio", ""),
            activo       = data.get("autorizado", False),
            encontrado   = True,
        )

    except httpx.TimeoutException:
        logger.warning("CRM Service: timeout obteniendo contexto de %r.", id_comercio)
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "CRM Service: HTTP %s para comercio %r.",
            exc.response.status_code, id_comercio,
        )
    except Exception as exc:
        logger.error(
            "CRM Service: error obteniendo contexto de %r | %s: %s",
            id_comercio, type(exc).__name__, exc,
        )

    return ComercioContexto(encontrado=False)


# ── 3. Config de Feedback (cliente compartido) ────────────────────────────────


async def obtener_config_feedback(comercio_uuid: str) -> dict:
    """Obtiene stats y configuración del Servicio de Feedback para un comercio.

    Úsalo para que el Recepcionista conozca el google_review_link del hotel
    y pueda invitar al huésped a dejar su reseña al despedirse.

    Args:
        comercio_uuid: UUID de ``ServicioFeedbackConfig`` en el CRM Django.

    Returns:
        Dict con métricas y config, o {} si la llamada falla.
    """
    try:
        response = await _client().get(
            "/api/v1/servicio-feedback/stats/",
            params={"comercio_id": comercio_uuid, "dias": 30},
        )
        if response.status_code == 200:
            return response.json()
        logger.warning(
            "CRM Service: stats HTTP %s para uuid=%r.", response.status_code, comercio_uuid
        )
    except Exception as exc:
        logger.warning(
            "CRM Service: error obteniendo config feedback | %s: %s",
            type(exc).__name__, exc,
        )

    return {}
