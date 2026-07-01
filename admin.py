"""
Panel de administración del Add-on "Servicio de Feedback", vía sqladmin
(equivalente a Django admin para FastAPI + SQLAlchemy).

sqladmin no tiene un decorador `@admin.register` como Django: el registro
moderno es `admin.add_view(MiModelView)` sobre la instancia de Admin.

Este panel expone api_token en texto plano, así que NO se monta sin
autenticación: reutiliza las credenciales y el rol 'admin' ya existentes en
auth.py / models.Usuario, en vez de crear un sistema de login paralelo.
"""
import os

from sqladmin import ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import select
from starlette.requests import Request

from auth import verify_password
from database import SessionLocal
from feedback_models import Organizacion, ServicioFeedbackConfig
from models import Usuario


class OrganizacionAdmin(ModelView, model=Organizacion):
    name = "Organización"
    name_plural = "Organizaciones"
    icon = "fa-solid fa-building"

    column_list = [Organizacion.nombre, Organizacion.activa, Organizacion.created_at]
    column_searchable_list = [Organizacion.nombre]
    column_sortable_list = [Organizacion.nombre, Organizacion.created_at]


class ServicioFeedbackConfigAdmin(ModelView, model=ServicioFeedbackConfig):
    name = "Configuración de Feedback"
    name_plural = "Configuraciones de Feedback"
    icon = "fa-solid fa-star"

    # 1. Listado principal: organización, tipo de negocio, estado, última sync.
    #    "organizacion" se muestra vía Organizacion.__str__ (devuelve el nombre).
    column_list = [
        ServicioFeedbackConfig.organizacion,
        ServicioFeedbackConfig.tipo_negocio,
        ServicioFeedbackConfig.estado_suscripcion,
        ServicioFeedbackConfig.ultima_sincronizacion,
    ]
    column_labels = {
        ServicioFeedbackConfig.organizacion: "Organización",
        ServicioFeedbackConfig.tipo_negocio: "Tipo de negocio",
        ServicioFeedbackConfig.estado_suscripcion: "Estado",
        ServicioFeedbackConfig.ultima_sincronizacion: "Última sincronización",
    }

    # 2. Filtros por estado_suscripcion y tipo_negocio.
    column_filters = [
        ServicioFeedbackConfig.estado_suscripcion,
        ServicioFeedbackConfig.tipo_negocio,
    ]

    # 3. Búsqueda por el nombre de la organización asociada (requiere el
    #    string con dot-path; sqladmin resuelve el JOIN automáticamente).
    column_searchable_list = ["organizacion.nombre"]

    # 4. id y api_token visibles pero de solo lectura: se incluyen en el
    #    formulario (form_include_pk + form_columns) y se renderizan con el
    #    atributo HTML "readonly" (visibles/copiables, no editables).
    form_include_pk = True
    form_columns = [
        ServicioFeedbackConfig.id,
        ServicioFeedbackConfig.organizacion,
        ServicioFeedbackConfig.estado_suscripcion,
        ServicioFeedbackConfig.tipo_negocio,
        ServicioFeedbackConfig.google_sheet_url,
        ServicioFeedbackConfig.google_review_link,
        ServicioFeedbackConfig.api_token,
    ]
    form_widget_args = {
        "id": {"readonly": True},
        "api_token": {"readonly": True},
    }

    column_default_sort = [(ServicioFeedbackConfig.ultima_sincronizacion.name, True)]


def registrar(admin) -> None:
    """Registra las vistas del Add-on sobre una instancia de sqladmin.Admin."""
    admin.add_view(OrganizacionAdmin)
    admin.add_view(ServicioFeedbackConfigAdmin)


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------


class AdminAuth(AuthenticationBackend):
    """Login del panel sqladmin contra la misma tabla `usuarios` del CRM.

    Solo usuarios con rol 'admin' (no 'soporte') pueden entrar, porque acá se
    ve el api_token de cada comercio en texto plano.
    """

    async def login(self, request: Request) -> bool:
        form = await request.form()
        username, password = form.get("username", ""), form.get("password", "")

        db = SessionLocal()
        try:
            usuario = db.scalars(
                select(Usuario).where(Usuario.username == username)
            ).first()
            if (
                not usuario
                or not usuario.activo
                or usuario.rol != "admin"
                or not verify_password(password, usuario.hashed_password)
            ):
                return False
            request.session.update({"usuario_admin": usuario.username})
            return True
        finally:
            db.close()

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        username = request.session.get("usuario_admin")
        if not username:
            return False

        db = SessionLocal()
        try:
            usuario = db.scalars(
                select(Usuario).where(Usuario.username == username)
            ).first()
            return bool(usuario and usuario.activo and usuario.rol == "admin")
        finally:
            db.close()


def crear_auth_backend() -> AdminAuth:
    secret_key = os.environ.get("JWT_SECRET_KEY", "")
    if not secret_key:
        raise RuntimeError("JWT_SECRET_KEY no configurada en el entorno")
    return AdminAuth(secret_key=secret_key)
