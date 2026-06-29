"""
bot_guard.py — Guardia de acceso reutilizable para bots de DM Global.

Verifica contra /api/v1/validar-acceso antes de que el bot inicialice
cualquier recurso costoso (navegador, proxies, conexiones externas).

Estrategia fail-closed: ante cualquier error de red o configuración,
se deniega el acceso para no consumir recursos sin autorización.

Variables de entorno requeridas:
    DMGLOBAL_API_URL        Base URL de la API (ej: http://api.dmglobal.com)
    DMGLOBAL_BOT_API_KEY    Token secreto X-API-Key

Variable opcional:
    DMGLOBAL_TIMEOUT        Segundos máximos de espera (default: 8)
"""

import asyncio
import functools
import logging
import os
import sys
from typing import Any, Callable

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuración desde entorno
# ---------------------------------------------------------------------------

_API_BASE_URL: str = os.environ.get("DMGLOBAL_API_URL", "http://localhost:8000").rstrip("/")
_BOT_API_KEY: str = os.environ.get("DMGLOBAL_BOT_API_KEY", "")
_TIMEOUT: int = int(os.environ.get("DMGLOBAL_TIMEOUT", "8"))

_ENDPOINT = f"{_API_BASE_URL}/api/v1/validar-acceso"


# ---------------------------------------------------------------------------
# Función de validación central
# ---------------------------------------------------------------------------


def validar_acceso(cuit: str, nombre_servicio: str) -> tuple[bool, str]:
    """Consulta el endpoint de validación y retorna (autorizado, motivo).

    Siempre retorna False ante cualquier error de configuración o red —
    el bot nunca debe correr si no se puede confirmar la autorización.
    """
    if not _BOT_API_KEY:
        logger.critical(
            "DMGLOBAL_BOT_API_KEY no configurada — no se puede validar el acceso"
        )
        return False, "api_key_no_configurada"

    try:
        resp = requests.get(
            _ENDPOINT,
            params={"cuit": cuit, "nombre_servicio": nombre_servicio},
            headers={
                "X-API-Key": _BOT_API_KEY,
                "User-Agent": f"DMGlobal-Bot/{nombre_servicio}",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data: dict = resp.json()
        autorizado: bool = data.get("autorizado", False)
        estado: str = data.get("estado", "desconocido")
        return autorizado, estado

    except requests.exceptions.Timeout:
        logger.error(
            "Timeout al validar acceso | url=%s timeout=%ds cuit=%s",
            _ENDPOINT, _TIMEOUT, cuit,
        )
        return False, "timeout"

    except requests.exceptions.ConnectionError:
        logger.error(
            "Sin conexión con la API de validación | url=%s cuit=%s",
            _ENDPOINT, cuit,
        )
        return False, "connection_error"

    except requests.exceptions.HTTPError as exc:
        codigo = exc.response.status_code if exc.response is not None else "?"
        logger.error(
            "Error HTTP al validar acceso | status=%s cuit=%s",
            codigo, cuit,
        )
        return False, f"http_{codigo}"

    except Exception as exc:
        logger.error("Error inesperado al validar acceso: %s", exc)
        return False, "error_inesperado"


# ---------------------------------------------------------------------------
# Guardia imperativo (para uso sin decorador)
# ---------------------------------------------------------------------------


def verificar_licencia_dm_global(cuit: str, nombre_servicio: str) -> bool:
    """Verifica si el CUIT tiene una suscripción activa para el servicio indicado.

    Función de integración directa para bots: retorna True si el acceso está
    autorizado. Si no lo está, imprime el mensaje de denegación estándar de
    DM Global y termina el proceso con sys.exit(0) (cierre limpio, sin alertas
    de scheduler) antes de abrir navegadores, consumir proxies o hacer requests.

    Uso mínimo al inicio de cualquier bot:
        if not verificar_licencia_dm_global(CUIT, "Monitoreo Web"):
            pass  # nunca llega aquí; sys.exit(0) ya fue llamado

        # A partir de aquí el acceso está garantizado
        browser = playwright.chromium.launch(...)
    """
    autorizado, estado = validar_acceso(cuit, nombre_servicio)

    if autorizado:
        logger.info("[DM Global] Acceso autorizado | cuit=%s servicio=%s", cuit, nombre_servicio)
        return True

    logger.warning(
        "[DM Global] Ejecución denegada para el CUIT %s: Suscripción %s.",
        cuit, estado,
    )
    print(
        f"[DM Global] Ejecución denegada para el CUIT {cuit}: "
        f"Suscripción {estado}.",
        flush=True,
    )
    sys.exit(0)


def abortar_si_no_autorizado(cuit: str, nombre_servicio: str, bot_id: str = "") -> None:
    """Valida el acceso y termina el proceso con sys.exit(1) si no está autorizado.

    Diseñado para llamarse al inicio del script, antes de cualquier
    inicialización de recursos (navegador, proxies, etc.).

    Ejemplo de uso:
        abortar_si_no_autorizado(cuit=CUIT, nombre_servicio="Monitoreo Web")
        # Si llega aquí, el acceso fue confirmado
        browser = chromium.launch(...)
    """
    tag = bot_id or nombre_servicio
    logger.info("Validando acceso | bot=%s cuit=%s servicio=%s", tag, cuit, nombre_servicio)

    autorizado, estado = validar_acceso(cuit, nombre_servicio)

    if autorizado:
        logger.info("Acceso AUTORIZADO | bot=%s cuit=%s", tag, cuit)
        return

    logger.warning(
        "Acceso DENEGADO — abortando antes de inicializar recursos | "
        "bot=%s cuit=%s servicio=%s estado=%s",
        tag, cuit, nombre_servicio, estado,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Decorador reutilizable (sync y async)
# ---------------------------------------------------------------------------


def requiere_suscripcion_activa(cuit: str, nombre_servicio: str, bot_id: str = "") -> Callable:
    """Decorador que protege la función del bot verificando la suscripción.

    Compatible con funciones síncronas y corrutinas async.
    Si la suscripción no está activa, aborta con sys.exit(1) antes de
    ejecutar el cuerpo de la función (y por tanto antes de abrir navegadores
    o consumir proxies).

    Args:
        cuit:           CUIT/CUIL del cliente (solo dígitos).
        nombre_servicio: Nombre exacto del servicio en el CRM.
        bot_id:         Identificador opcional para los logs (default: nombre_servicio).

    Ejemplo:
        @requiere_suscripcion_activa(
            cuit=os.environ["CUIT_CLIENTE"],
            nombre_servicio="Monitoreo Web",
            bot_id="bot-monitoreo-01",
        )
        def ejecutar():
            ...
    """
    def decorator(func: Callable) -> Callable:
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                abortar_si_no_autorizado(cuit, nombre_servicio, bot_id)
                return await func(*args, **kwargs)
            return _async_wrapper
        else:
            @functools.wraps(func)
            def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                abortar_si_no_autorizado(cuit, nombre_servicio, bot_id)
                return func(*args, **kwargs)
            return _sync_wrapper

    return decorator
