"""
Dispatcher de eventos salientes hacia n8n, Zapier u otros webhooks HTTP.

Uso:
    from notifier import notificar_cambio_estado
    # Llamar desde un BackgroundTask de FastAPI para no bloquear la respuesta.
    background_tasks.add_task(
        notificar_cambio_estado,
        cuit="20123456789",
        nombre_servicio="Monitoreo Web",
        nuevo_estado="activa",
        pasarela="stripe",
        suscripcion_id=42,
    )

Variable de entorno requerida:
    OUTGOING_WEBHOOK_URLS — URLs separadas por coma (n8n, Zapier, etc.)
    Ejemplo: https://n8n.dmglobal.com/webhook/crm,https://hooks.zapier.com/hooks/catch/123/abc
"""

import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

# Lista de destinos construida una sola vez al importar el módulo
_DESTINOS: list[str] = [
    url.strip()
    for url in os.environ.get("OUTGOING_WEBHOOK_URLS", "").split(",")
    if url.strip()
]


async def notificar_cambio_estado(
    *,
    cuit: str,
    nombre_servicio: str,
    nuevo_estado: str,
    pasarela: str,
    suscripcion_id: int,
) -> None:
    """Envía un POST a cada URL configurada con los datos del cambio de estado.

    Diseñado para ejecutarse en background: captura todas las excepciones
    para que un fallo de red no afecte la respuesta principal al cliente.
    """
    if not _DESTINOS:
        logger.debug("OUTGOING_WEBHOOK_URLS vacío — notificación omitida")
        return

    payload = {
        "cuit": cuit,
        "nombre_servicio": nombre_servicio,
        "nuevo_estado": nuevo_estado,
        "pasarela": pasarela,
        "suscripcion_id": suscripcion_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        for url in _DESTINOS:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                logger.info(
                    "Notificación enviada | url=%s estado=%s cuit=%s",
                    url, nuevo_estado, cuit,
                )
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "Destino rechazó la notificación | url=%s status=%d cuit=%s",
                    url, exc.response.status_code, cuit,
                )
            except httpx.HTTPError as exc:
                logger.error(
                    "Error de red enviando notificación | url=%s error=%s",
                    url, exc,
                )
