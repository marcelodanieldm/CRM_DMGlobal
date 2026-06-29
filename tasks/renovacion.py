"""
Cron job diario — Expiración automática de suscripciones vencidas.

Lógica:
  1. Busca todas las suscripciones 'activa' con fecha_proxima_renovacion <= ahora.
  2. Las pasa a 'pausada' en batch.
  3. Registra un AuditLog por cada una con accion='expiracion_automatica'.
  4. Dispara la notificación saliente hacia n8n/Zapier por cada suscripción.

Concurrencia:
  - La consulta/escritura corre en asyncio.to_thread (sync SQLAlchemy en thread pool)
    para no bloquear el event loop de FastAPI.
  - Las notificaciones se lanzan con await en el hilo del event loop.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from database import SessionLocal
from models import AuditLog, Suscripcion
from notifier import notificar_cambio_estado

logger = logging.getLogger(__name__)


def _pausar_vencidas_sync() -> list[dict]:
    """Ejecuta la lectura y escritura en DB dentro de un thread pool.

    Retorna la lista de datos necesarios para notificar, capturados
    ANTES del commit (SQLAlchemy expira atributos tras commit por defecto).
    """
    db = SessionLocal()
    try:
        ahora = datetime.now(timezone.utc)

        subs_vencidas = db.scalars(
            select(Suscripcion)
            .options(
                joinedload(Suscripcion.cliente),
                joinedload(Suscripcion.servicio),
            )
            .where(
                Suscripcion.estado_suscripcion == "activa",
                Suscripcion.fecha_proxima_renovacion <= ahora,
            )
        ).all()

        if not subs_vencidas:
            logger.info("Cron renovaciones | sin suscripciones vencidas")
            return []

        logger.info(
            "Cron renovaciones | %d suscripción(es) a pausar",
            len(subs_vencidas),
        )

        # Capturar datos de notificación ANTES del commit
        datos_notificacion = [
            {
                "cuit": sub.cliente.cuit_cuil,
                "nombre_servicio": sub.servicio.nombre,
                "suscripcion_id": sub.id,
                "fecha_vencida": str(sub.fecha_proxima_renovacion.date()),
            }
            for sub in subs_vencidas
        ]

        for sub in subs_vencidas:
            sub.estado_suscripcion = "pausada"
            sub.fecha_ultima_pausa = ahora
            db.add(
                AuditLog(
                    suscripcion_id=sub.id,
                    usuario_interno="sistema:cron",
                    accion="expiracion_automatica",
                    detalles=(
                        f"renovacion_vencida={sub.fecha_proxima_renovacion.date()} "
                        f"cuit={sub.cliente.cuit_cuil} "
                        f"servicio={sub.servicio.nombre}"
                    ),
                )
            )

        db.commit()
        logger.info(
            "Cron renovaciones | %d suscripción(es) pausadas correctamente",
            len(subs_vencidas),
        )
        return datos_notificacion

    except Exception as exc:
        db.rollback()
        logger.error("Cron renovaciones | error al procesar: %s", exc, exc_info=True)
        return []
    finally:
        db.close()


async def verificar_renovaciones_vencidas() -> None:
    """Entry point del cron job — invocado por APScheduler una vez al día.

    Separa la operación bloqueante de DB (thread) de las notificaciones async.
    """
    logger.info("Cron renovaciones | iniciando verificación periódica")

    datos = await asyncio.to_thread(_pausar_vencidas_sync)

    for item in datos:
        await notificar_cambio_estado(
            cuit=item["cuit"],
            nombre_servicio=item["nombre_servicio"],
            nuevo_estado="pausada",
            pasarela="sistema:cron",
            suscripcion_id=item["suscripcion_id"],
        )

    logger.info(
        "Cron renovaciones | ciclo completo — %d notificaciones enviadas",
        len(datos),
    )
