"""
Endpoints de autenticación — login y utilidades de usuarios internos.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, field_validator
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
    email: EmailStr
    password: str
    rol: str = "soporte"

    @field_validator("password")
    @classmethod
    def validar_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres")
        if not any(c.isdigit() for c in v):
            raise ValueError("La contraseña debe contener al menos un número")
        if not any(c.isupper() for c in v):
            raise ValueError("La contraseña debe contener al menos una mayúscula")
        return v

    @field_validator("rol")
    @classmethod
    def validar_rol(cls, v: str) -> str:
        if v not in ("admin", "soporte"):
            raise ValueError("rol debe ser 'admin' o 'soporte'")
        return v


class UsuarioUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    rol: Optional[str] = None
    activo: Optional[bool] = None

    @field_validator("rol")
    @classmethod
    def validar_rol(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("admin", "soporte"):
            raise ValueError("rol debe ser 'admin' o 'soporte'")
        return v


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


@router.put(
    "/usuarios/{usuario_id}",
    response_model=UsuarioRead,
    dependencies=[Depends(require_admin)],
)
def actualizar_usuario(usuario_id: int, payload: UsuarioUpdate, db: DbDep) -> Usuario:
    """Actualiza rol y/o estado de un usuario. Solo administradores."""
    usuario = db.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )
    cambios = payload.model_dump(exclude_unset=True)
    for campo, valor in cambios.items():
        setattr(usuario, campo, valor)
    db.commit()
    db.refresh(usuario)
    return usuario
