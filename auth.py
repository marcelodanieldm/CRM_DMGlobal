"""
Módulo de autenticación y autorización.

Responsabilidades:
  - Hash/verificación de contraseñas con bcrypt (passlib).
  - Generación y decodificación de JWT (python-jose).
  - Dependencias FastAPI para obtener el usuario actual y verificar roles.

Variables de entorno requeridas:
    JWT_SECRET_KEY      Clave secreta para firmar los tokens (mínimo 32 chars).

Variables opcionales:
    JWT_EXPIRY_MINUTES  Duración del token en minutos (default: 480 = 8 horas).
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import Usuario

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

_SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", "")
_ALGORITHM = "HS256"
_TOKEN_EXPIRY_MINUTES: int = int(os.environ.get("JWT_EXPIRY_MINUTES", "480"))

_crypt = CryptContext(schemes=["bcrypt"], deprecated="auto")

# La URL debe coincidir con el prefix del router de login
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# ---------------------------------------------------------------------------
# Utilidades de contraseñas
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return _crypt.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _crypt.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def crear_token(username: str, rol: str) -> str:
    if not _SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY no configurada en el entorno")
    expiry = datetime.now(timezone.utc) + timedelta(minutes=_TOKEN_EXPIRY_MINUTES)
    return jwt.encode(
        {"sub": username, "rol": rol, "exp": expiry},
        _SECRET_KEY,
        algorithm=_ALGORITHM,
    )


# ---------------------------------------------------------------------------
# Dependencia base: usuario autenticado
# ---------------------------------------------------------------------------

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="No autenticado o token inválido",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_usuario_actual(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> Usuario:
    """Decodifica el JWT, valida la firma y devuelve el Usuario activo.

    Lanza 401 ante cualquier problema: token malformado, expirado,
    usuario inexistente o inactivo.
    """
    if not _SECRET_KEY:
        raise _CREDENTIALS_EXC

    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
        username: str = payload.get("sub", "")
        if not username:
            raise _CREDENTIALS_EXC
    except JWTError:
        raise _CREDENTIALS_EXC

    usuario = db.scalars(
        select(Usuario).where(Usuario.username == username)
    ).first()

    if not usuario or not usuario.activo:
        raise _CREDENTIALS_EXC

    return usuario


# Tipo anotado reutilizable para inyectar el usuario en cualquier endpoint
UsuarioActual = Annotated[Usuario, Depends(get_usuario_actual)]


# ---------------------------------------------------------------------------
# Dependencias de roles
# ---------------------------------------------------------------------------


def require_admin(usuario: UsuarioActual) -> Usuario:
    """Permite el acceso solo a usuarios con rol 'admin'. Lanza 403 si no."""
    if usuario.rol != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido: se requiere rol 'admin'",
        )
    return usuario


def require_admin_o_soporte(usuario: UsuarioActual) -> Usuario:
    """Permite el acceso a usuarios con rol 'admin' o 'soporte'. Lanza 403 si no."""
    if usuario.rol not in ("admin", "soporte"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido: se requiere rol 'admin' o 'soporte'",
        )
    return usuario
