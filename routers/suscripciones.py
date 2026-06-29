"""
Router de Suscripciones — gestión del ciclo de vida de los contratos.

Endpoints:
    GET  /api/v1/suscripciones/           Lista, filtrable por cliente_id
    POST /api/v1/suscripciones/           Alta de nueva suscripción
    PUT  /api/v1/suscripciones/{id}/estado  Cambio de estado (con RBAC granular)
"""

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from auth import get_usuario_actual, require_admin_o_soporte
from database import get_db
from models import AuditLog, Servicio, Suscripcion, Usuario

router = APIRouter(prefix="/api/v1/suscripciones", tags=["suscripciones"])

DbDep = Annotated[Session, Depends(get_db)]
UsuarioActual = Annotated[Usuario, Depends(get_usuario_actual)]
AdminOSoporte = Annotated[Usuario, Depends(require_admin_o_soporte)]

_ESTADOS_VALIDOS = {"activa", "pausada", "desactivada"}


# ---------------------------------------------------------------------------
# Schemas de entrada / salida
# ---------------------------------------------------------------------------


class SuscripcionCreate(BaseModel):
    cliente_id: int
    servicio_id: int
    precio_acordado: Optional[float] = None
    pasarela_pago: str

    @field_validator("pasarela_pago")
    @classmethod
    def validar_pasarela(cls, v: str) -> str:
        if v not in {"mercadopago", "stripe", "manual"}:
            raise ValueError("pasarela_pago inválida")
        return v


class EstadoUpdate(BaseModel):
    estado: str

    @field_validator("estado")
    @classmethod
    def validar_estado(cls, v: str) -> str:
        if v not in _ESTADOS_VALIDOS:
            raise ValueError(f"estado debe ser uno de {_ESTADOS_VALIDOS}")
        return v


class SuscripcionRead(BaseModel):
    """Schema plano que incluye datos del Servicio relacionado.
    Diseñado para el consumo directo del frontend sin lookups adicionales."""

    id: int
    cliente_id: int
    servicio_id: int
    servicio_nombre: str
    tipo_ejecucion: str
    precio_base: float
    precio_acordado: Optional[float]
    estado_suscripcion: str
    pasarela_pago: str
    externa_id: Optional[str]
    fecha_inicio: datetime
    fecha_proxima_renovacion: Optional[datetime]
    fecha_ultima_pausa: Optional[datetime]

    @classmethod
    def from_orm(cls, sub: Suscripcion) -> "SuscripcionRead":
        return cls(
            id=sub.id,
            cliente_id=sub.cliente_id,
            servicio_id=sub.servicio_id,
            servicio_nombre=sub.servicio.nombre,
            tipo_ejecucion=sub.servicio.tipo_ejecucion,
            precio_base=sub.servicio.precio_base,
            precio_acordado=sub.precio_acordado,
            estado_suscripcion=sub.estado_suscripcion,
            pasarela_pago=sub.pasarela_pago,
            externa_id=sub.externa_id,
            fecha_inicio=sub.fecha_inicio,
            fecha_proxima_renovacion=sub.fecha_proxima_renovacion,
            fecha_ultima_pausa=sub.fecha_ultima_pausa,
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[SuscripcionRead])
def listar_suscripciones(
    db: DbDep,
    _u: AdminOSoporte,
    cliente_id: Optional[int] = Query(None, description="Filtrar por cliente"),
) -> list[SuscripcionRead]:
    stmt = select(Suscripcion).options(joinedload(Suscripcion.servicio))
    if cliente_id is not None:
        stmt = stmt.where(Suscripcion.cliente_id == cliente_id)
    subs = db.scalars(stmt).unique().all()
    return [SuscripcionRead.from_orm(s) for s in subs]


@router.post("/", response_model=SuscripcionRead, status_code=status.HTTP_201_CREATED)
def crear_suscripcion(
    payload: SuscripcionCreate,
    db: DbDep,
    usuario: UsuarioActual,
) -> SuscripcionRead:
    """Alta de suscripción. Solo admin puede asignar servicios a clientes."""
    if usuario.rol != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores pueden asignar servicios",
        )

    servicio = db.get(Servicio, payload.servicio_id)
    if not servicio or not servicio.activo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servicio no encontrado o inactivo")

    sub = Suscripcion(
        cliente_id=payload.cliente_id,
        servicio_id=payload.servicio_id,
        precio_acordado=payload.precio_acordado,
        pasarela_pago=payload.pasarela_pago,
        estado_suscripcion="activa",
    )
    db.add(sub)
    db.flush()  # obtiene el ID antes del commit

    db.add(AuditLog(
        suscripcion_id=sub.id,
        usuario_interno=usuario.username,
        accion="nueva_suscripcion",
        detalles=(
            f"servicio={servicio.nombre} "
            f"precio_acordado={payload.precio_acordado or servicio.precio_base} "
            f"pasarela={payload.pasarela_pago}"
        ),
    ))
    db.commit()
    db.refresh(sub)
    return SuscripcionRead.from_orm(sub)


@router.put("/{suscripcion_id}/estado", response_model=SuscripcionRead)
def actualizar_estado(
    suscripcion_id: int,
    payload: EstadoUpdate,
    db: DbDep,
    usuario: UsuarioActual,
) -> SuscripcionRead:
    """Cambia el estado de una suscripción con RBAC granular.

    Reglas de rol:
      admin   → puede establecer cualquier estado (activa, pausada, desactivada)
      soporte → solo puede activar o pausar (no puede dar de baja)
    """
    if usuario.rol not in ("admin", "soporte"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permiso insuficiente")

    if usuario.rol == "soporte" and payload.estado == "desactivada":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El rol 'soporte' no puede dar de baja una suscripción",
        )

    sub = db.scalars(
        select(Suscripcion)
        .options(joinedload(Suscripcion.servicio))
        .where(Suscripcion.id == suscripcion_id)
    ).first()

    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suscripción no encontrada")

    estado_anterior = sub.estado_suscripcion
    sub.estado_suscripcion = payload.estado
    if payload.estado == "pausada":
        sub.fecha_ultima_pausa = datetime.now(timezone.utc)

    db.add(AuditLog(
        suscripcion_id=sub.id,
        usuario_interno=usuario.username,
        accion=f"estado:{estado_anterior}→{payload.estado}",
        detalles=f"actualización manual · panel web",
    ))
    db.commit()
    db.refresh(sub)
    return SuscripcionRead.from_orm(sub)
