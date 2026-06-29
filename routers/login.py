"""
Endpoints de autenticación — login y utilidades de usuarios internos.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import crear_token, hash_password, require_admin, verify_password
from database import get_db
from models import Usuario

router = APIRouter(prefix="/api/v1/auth", tags=["autenticación"])

DbDep = Annotated[Session, Depends(get_db)]


# ---------------------------------------------------------------------------
# Schemas de respuesta
# ---------------------------------------------------------------------------


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UsuarioCreate(BaseModel):
    username: str
    email: str
    password: str
    rol: str = "soporte"


class UsuarioRead(BaseModel):
    id: int
    username: str
    email: str
    rol: str
    activo: bool

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@router.post("/login", response_model=TokenResponse)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbDep,
) -> TokenResponse:
    """Autentica un usuario interno y devuelve un JWT Bearer.

    El formulario usa `application/x-www-form-urlencoded` (estándar OAuth2):
      - username
      - password
    """
    usuario = db.scalars(
        select(Usuario).where(Usuario.username == form.username)
    ).first()

    if not usuario or not usuario.activo or not verify_password(form.password, usuario.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = crear_token(username=usuario.username, rol=usuario.rol)
    return TokenResponse(access_token=token)


# ---------------------------------------------------------------------------
# Gestión de usuarios (solo admin)
# ---------------------------------------------------------------------------


@router.post(
    "/usuarios",
    response_model=UsuarioRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def crear_usuario(payload: UsuarioCreate, db: DbDep) -> Usuario:
    """Crea un usuario interno. Solo accesible para administradores."""
    if payload.rol not in ("admin", "soporte"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="rol debe ser 'admin' o 'soporte'",
        )
    usuario = Usuario(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        rol=payload.rol,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@router.get(
    "/usuarios",
    response_model=list[UsuarioRead],
    dependencies=[Depends(require_admin)],
)
def listar_usuarios(db: DbDep) -> list[Usuario]:
    """Lista todos los usuarios internos. Solo accesible para administradores."""
    return list(db.scalars(select(Usuario)).all())
