"""
Endpoint público de validación para el Add-on "Servicio de Feedback".

Consumido por Google Apps Script (UrlFetchApp) desde la planilla de cada
comercio, sin sesión ni cookies de por medio. La autenticación es por dos
UUIDs en el query string: comercio_id (PK de ServicioFeedbackConfig) y
token (su api_token).

Diseño de seguridad:
- comercio_id con formato de UUID inválido, comercio_id inexistente y token
  incorrecto devuelven exactamente el mismo 401 genérico (mismo status,
  mismo detail), para no filtrar si un comercio_id existe en la base.
- El token se compara siempre como string en tiempo constante
  (secrets.compare_digest), incluso cuando comercio_id no existe, contra un
  valor dummy — así el tiempo de respuesta no delata la existencia del
  registro (mitiga timing attacks).
- Las respuestas de error no incluyen trazas ni detalles internos.
"""

import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from feedback_models import ServicioFeedbackConfig

router = APIRouter(prefix="/api/v1/servicio-feedback", tags=["servicio-feedback"])

# Usado para comparar en tiempo constante cuando comercio_id no existe,
# de forma que el costo de la comparación sea el mismo que con un registro real.
_TOKEN_DUMMY = str(uuid.uuid4())

_DETALLE_NO_AUTORIZADO = "Credenciales inválidas"


class RespuestaValidacion(BaseModel):
    autorizado: bool
    nombre_comercio: str
    tipo_negocio: str
    google_review_link: str


def _no_autorizado() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_DETALLE_NO_AUTORIZADO)


@router.get(
    "/validar/",
    response_model=RespuestaValidacion,
    summary="Valida comercio_id + token para el widget de feedback",
    description=(
        "Endpoint público (sin sesión) consultado por Google Apps Script. "
        "Recibe `comercio_id` (UUID de la configuración) y `token` (api_token) "
        "por query string."
    ),
)
def validar_comercio(
    db: Annotated[Session, Depends(get_db)],
    comercio_id: Annotated[str, Query(description="UUID de ServicioFeedbackConfig")],
    token: Annotated[str, Query(description="UUID del api_token asignado al comercio")],
) -> RespuestaValidacion:
    try:
        comercio_uuid = uuid.UUID(comercio_id)
    except ValueError:
        # Formato inválido: mismo 401 genérico que credenciales incorrectas,
        # nunca un 422 que delate el motivo exacto del rechazo.
        raise _no_autorizado()

    config = db.get(ServicioFeedbackConfig, comercio_uuid)

    # El token se compara siempre, exista o no el registro, para mantener
    # un costo (y un tiempo de respuesta) equivalente en ambos casos.
    token_real = str(config.api_token) if config is not None else _TOKEN_DUMMY
    token_valido = secrets.compare_digest(token_real, token)

    if config is None or not token_valido:
        raise _no_autorizado()

    if config.estado_suscripcion == "INACTIVO":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La suscripción del comercio está inactiva",
        )

    # estado_suscripcion solo admite ACTIVO, INACTIVO o DEMO (Enum de BD);
    # llegado a este punto solo quedan ACTIVO y DEMO.
    return RespuestaValidacion(
        autorizado=True,
        nombre_comercio=config.organizacion.nombre,
        tipo_negocio=config.tipo_negocio,
        google_review_link=config.google_review_link,
    )
