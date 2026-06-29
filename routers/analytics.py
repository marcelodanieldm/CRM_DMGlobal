"""
Router de Analytics — KPIs de salud de servicios y exportación CSV.

Todos los endpoints están restringidos a usuarios con rol 'admin'.

Endpoints:
    GET /api/v1/analytics/servicios/salud
        → JSON con métricas agregadas por servicio (clientes activos, MRR, tasa de éxito).

    GET /api/v1/analytics/servicios/{servicio_id}/exportar
        → Archivo CSV descargable con el historial de suscripciones del servicio.
"""

import csv
import math
from datetime import datetime, timezone
from io import StringIO
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload

from auth import require_admin
from database import get_db
from models import Cliente, Servicio, Suscripcion

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

DbDep    = Annotated[Session, Depends(get_db)]
SoloAdmin = Depends(require_admin)


# ---------------------------------------------------------------------------
# Schema de respuesta del endpoint de salud
# ---------------------------------------------------------------------------


class ServicioSaludRead(BaseModel):
    id: int
    nombre_servicio: str
    clientes_activos: int
    mrr_generado: float
    tasa_exito_promedio: float   # simulado hasta integrar logs de bots


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tasa_simulada(servicio_id: int) -> float:
    """Genera una tasa de éxito determinista por servicio_id.

    Fórmula: variación sinusoidal entre 95.0 y 99.5 %.
    En producción, reemplazar con una consulta a la tabla de logs de bots.
    """
    return round(97.2 + math.sin(servicio_id * 1.3) * 2.2, 1)


# ---------------------------------------------------------------------------
# GET /api/v1/analytics/servicios/salud
# ---------------------------------------------------------------------------


@router.get(
    "/servicios/salud",
    response_model=list[ServicioSaludRead],
    dependencies=[SoloAdmin],
)
def salud_servicios(db: DbDep) -> list[ServicioSaludRead]:
    """Retorna métricas agregadas de salud por cada servicio activo del catálogo.

    Realiza un único LEFT JOIN con agregaciones para evitar N+1 queries:
      - clientes_activos: COUNT de suscripciones con estado='activa'
      - mrr_generado:     SUM(precio_acordado) de suscripciones activas.
                          Si precio_acordado es NULL, usa precio_base del servicio.
    """
    stmt = (
        select(
            Servicio.id,
            Servicio.nombre,
            func.count(
                case((Suscripcion.estado_suscripcion == "activa", 1), else_=None)
            ).label("clientes_activos"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Suscripcion.estado_suscripcion == "activa",
                            func.coalesce(Suscripcion.precio_acordado, Servicio.precio_base),
                        ),
                        else_=None,
                    )
                ),
                0.0,
            ).label("mrr_generado"),
        )
        .outerjoin(Suscripcion, Suscripcion.servicio_id == Servicio.id)
        .where(Servicio.activo == True)  # noqa: E712
        .group_by(Servicio.id, Servicio.nombre)
        .order_by(Servicio.nombre)
    )

    rows = db.execute(stmt).all()

    return [
        ServicioSaludRead(
            id=row.id,
            nombre_servicio=row.nombre,
            clientes_activos=row.clientes_activos,
            mrr_generado=float(row.mrr_generado),
            tasa_exito_promedio=_tasa_simulada(row.id),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# GET /api/v1/analytics/servicios/{servicio_id}/exportar
# ---------------------------------------------------------------------------


@router.get(
    "/servicios/{servicio_id}/exportar",
    dependencies=[SoloAdmin],
    response_class=StreamingResponse,
    summary="Exporta el historial de suscripciones de un servicio como CSV",
)
def exportar_csv(servicio_id: int, db: DbDep) -> StreamingResponse:
    """Genera y descarga un CSV con todas las suscripciones históricas del servicio.

    Headers de respuesta:
        Content-Type:        text/csv; charset=utf-8
        Content-Disposition: attachment; filename=reporte_servicio_{id}.csv

    Columnas del CSV:
        Razón Social, CUIT/CUIL, Precio Acordado (ARS),
        Estado Suscripción, Pasarela de Pago, Fecha de Inicio
    """
    # Verificar que el servicio existe
    servicio = db.get(Servicio, servicio_id)
    if servicio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Servicio no encontrado",
        )

    # Consulta con JOIN para obtener datos del cliente
    stmt = (
        select(
            Cliente.razon_social,
            Cliente.cuit_cuil,
            func.coalesce(Suscripcion.precio_acordado, Servicio.precio_base).label("precio"),
            Suscripcion.estado_suscripcion,
            Suscripcion.pasarela_pago,
            Suscripcion.fecha_inicio,
        )
        .join(Suscripcion.cliente)
        .join(Suscripcion.servicio)
        .where(Suscripcion.servicio_id == servicio_id)
        .order_by(Suscripcion.fecha_inicio.desc())
    )

    rows = db.execute(stmt).all()

    # Construir el CSV en memoria con la librería nativa de Python
    output = StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_NONNUMERIC)

    # Encabezado
    writer.writerow([
        "Razón Social",
        "CUIT/CUIL",
        "Precio Acordado (ARS)",
        "Estado Suscripción",
        "Pasarela de Pago",
        "Fecha de Inicio",
    ])

    # Filas de datos
    for row in rows:
        fecha_str = (
            row.fecha_inicio.strftime("%Y-%m-%d %H:%M:%S")
            if row.fecha_inicio else ""
        )
        writer.writerow([
            row.razon_social,
            row.cuit_cuil,
            round(float(row.precio), 2),
            row.estado_suscripcion,
            row.pasarela_pago,
            fecha_str,
        ])

    # Timestamp para el nombre del archivo
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"reporte_servicio_{servicio_id}_{ts}.csv"

    output.seek(0)

    return StreamingResponse(
        content=iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
