from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import require_admin, require_admin_o_soporte
from database import get_db
from models import Servicio, Usuario
from schemas import ServicioCreate, ServicioRead, ServicioUpdate

router = APIRouter(prefix="/api/v1/servicios", tags=["servicios"])

DbDep = Annotated[Session, Depends(get_db)]

# Roles requeridos por tipo de operación:
#   Lectura  → admin + soporte
#   Escritura (crear / editar / eliminar lógico) → admin únicamente
SoporteOAdmin = Annotated[Usuario, Depends(require_admin_o_soporte)]
SoloAdmin = Annotated[Usuario, Depends(require_admin)]


@router.get("/", response_model=list[ServicioRead])
def listar_servicios(
    db: DbDep,
    _u: SoporteOAdmin,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    solo_activos: bool = True,
):
    """Lista servicios. Por defecto solo muestra los activos (solo_activos=True)."""
    stmt = select(Servicio)
    if solo_activos:
        stmt = stmt.where(Servicio.activo == True)  # noqa: E712
    return db.scalars(stmt.offset(skip).limit(limit)).all()


@router.get("/{servicio_id}", response_model=ServicioRead)
def obtener_servicio(servicio_id: int, db: DbDep, _u: SoporteOAdmin):
    servicio = db.get(Servicio, servicio_id)
    if servicio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servicio no encontrado")
    return servicio


@router.post("/", response_model=ServicioRead, status_code=status.HTTP_201_CREATED)
def crear_servicio(payload: ServicioCreate, db: DbDep, _u: SoloAdmin):
    """Crea un servicio. Valida que el nombre técnico no esté repetido."""
    existente = db.scalars(
        select(Servicio).where(Servicio.nombre == payload.nombre)
    ).first()
    if existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un servicio con el nombre '{payload.nombre}'",
        )

    servicio = Servicio(**payload.model_dump())
    db.add(servicio)
    db.commit()
    db.refresh(servicio)
    return servicio


@router.put("/{servicio_id}", response_model=ServicioRead)
def actualizar_servicio(servicio_id: int, payload: ServicioUpdate, db: DbDep, _u: SoloAdmin):
    """Modifica atributos del servicio (actualización parcial).

    Si se envía un nuevo nombre, verifica que no exista en otro servicio.
    """
    servicio = db.get(Servicio, servicio_id)
    if servicio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servicio no encontrado")

    cambios = payload.model_dump(exclude_unset=True)

    if "nombre" in cambios:
        conflicto = db.scalars(
            select(Servicio).where(
                Servicio.nombre == cambios["nombre"],
                Servicio.id != servicio_id,
            )
        ).first()
        if conflicto:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El nombre '{cambios['nombre']}' ya pertenece a otro servicio",
            )

    for campo, valor in cambios.items():
        setattr(servicio, campo, valor)

    db.commit()
    db.refresh(servicio)
    return servicio


@router.delete("/{servicio_id}", status_code=status.HTTP_200_OK)
def eliminar_servicio(servicio_id: int, db: DbDep, _u: SoloAdmin):
    """Soft delete: pasa activo=False para preservar el historial de suscripciones.

    Retorna HTTP 200 con el estado final del recurso (no 204) para que el
    cliente pueda confirmar que el servicio fue desactivado correctamente.
    """
    servicio = db.get(Servicio, servicio_id)
    if servicio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servicio no encontrado")

    if not servicio.activo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El servicio ya estaba desactivado",
        )

    servicio.activo = False
    db.commit()
    db.refresh(servicio)
    return {"id": servicio.id, "nombre": servicio.nombre, "activo": servicio.activo}
