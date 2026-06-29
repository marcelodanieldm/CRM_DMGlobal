from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models import Cliente
from schemas import ClienteCreate, ClienteRead, ClienteUpdate

router = APIRouter(prefix="/clientes", tags=["clientes"])

DbDep = Annotated[Session, Depends(get_db)]


@router.get("/", response_model=list[ClienteRead])
def listar_clientes(
    db: DbDep,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    estado: str | None = None,
):
    stmt = select(Cliente)
    if estado is not None:
        stmt = stmt.where(Cliente.estado_general == estado)
    return db.scalars(stmt.offset(skip).limit(limit)).all()


@router.get("/{cliente_id}", response_model=ClienteRead)
def obtener_cliente(cliente_id: int, db: DbDep):
    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
    return cliente


@router.post("/", response_model=ClienteRead, status_code=status.HTTP_201_CREATED)
def crear_cliente(payload: ClienteCreate, db: DbDep):
    cliente = Cliente(**payload.model_dump())
    db.add(cliente)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un cliente con CUIT/CUIL '{payload.cuit_cuil}'",
        )
    db.refresh(cliente)
    return cliente


@router.patch("/{cliente_id}", response_model=ClienteRead)
def actualizar_cliente(cliente_id: int, payload: ClienteUpdate, db: DbDep):
    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")

    cambios = payload.model_dump(exclude_unset=True)
    for campo, valor in cambios.items():
        setattr(cliente, campo, valor)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un cliente con CUIT/CUIL '{payload.cuit_cuil}'",
        )
    db.refresh(cliente)
    return cliente


@router.delete("/{cliente_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_cliente(cliente_id: int, db: DbDep):
    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
    db.delete(cliente)
    db.commit()
