"""
Endpoint de validación de acceso para bots de scraping internos.

El bot consulta este endpoint antes de ejecutar cualquier tarea para verificar
que el cliente tiene una suscripción activa para el servicio requerido.

Autenticación: cabecera X-API-Key con token estático configurado en BOT_API_KEY.
"""

import os
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import Cliente, Servicio, Suscripcion

router = APIRouter(prefix="/api/v1", tags=["validación-bots"])

_BOT_API_KEY: str = os.environ.get("BOT_API_KEY", "")


# ---------------------------------------------------------------------------
# Schema de respuesta
# ---------------------------------------------------------------------------


class RespuestaAcceso(BaseModel):
    autorizado: bool
    estado: str  # valor real de estado_suscripcion, o "no_encontrada" si no existe


# ---------------------------------------------------------------------------
# Dependencia de autenticación
# ---------------------------------------------------------------------------


def _verificar_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Valida la cabecera X-API-Key con comparación en tiempo constante
    para evitar ataques de timing."""
    if not _BOT_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BOT_API_KEY no configurada en el servidor",
        )
    if not x_api_key or not secrets.compare_digest(x_api_key, _BOT_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key inválida o ausente",
            headers={"WWW-Authenticate": "ApiKey"},
        )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/validar-acceso",
    response_model=RespuestaAcceso,
    summary="Valida si un cliente tiene acceso activo a un servicio",
    description=(
        "Consultado por scripts de scraping antes de ejecutarse. "
        "Requiere la cabecera **X-API-Key** con el token configurado en `BOT_API_KEY`."
    ),
)
def validar_acceso(
    cuit: Annotated[
        str,
        Query(description="CUIT o CUIL del cliente (solo dígitos, 10 u 11 caracteres)"),
    ],
    nombre_servicio: Annotated[
        str,
        Query(description="Nombre exacto del servicio a verificar"),
    ],
    db: Annotated[Session, Depends(get_db)],
    _auth: Annotated[None, Depends(_verificar_api_key)],
) -> RespuestaAcceso:
    # Query principal: busca suscripción activa en un único JOIN
    suscripcion_activa = db.scalars(
        select(Suscripcion)
        .join(Suscripcion.cliente)
        .join(Suscripcion.servicio)
        .where(
            Cliente.cuit_cuil == cuit,
            Servicio.nombre == nombre_servicio,
            Servicio.activo == True,  # noqa: E712
            Suscripcion.estado_suscripcion == "activa",
        )
        .limit(1)
    ).first()

    if suscripcion_activa:
        return RespuestaAcceso(autorizado=True, estado="activa")

    # Fallback: buscar cualquier suscripción existente para devolver su estado real.
    # Permite que el bot sepa si está "pausada", "desactivada" o directamente no existe.
    suscripcion_cualquiera = db.scalars(
        select(Suscripcion)
        .join(Suscripcion.cliente)
        .join(Suscripcion.servicio)
        .where(
            Cliente.cuit_cuil == cuit,
            Servicio.nombre == nombre_servicio,
        )
        .limit(1)
    ).first()

    estado_real = suscripcion_cualquiera.estado_suscripcion if suscripcion_cualquiera else "no_encontrada"
    return RespuestaAcceso(autorizado=False, estado=estado_real)
