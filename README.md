# CRM DMGlobal — Backend API

API interna para la gestión de clientes, servicios y suscripciones de DM Global. Controla el acceso de bots de scraping, sincroniza estados de pago con MercadoPago y Stripe, y dispara eventos automáticos hacia n8n/Zapier.

---

## Índice

- [Stack tecnológico](#stack-tecnológico)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Instalación y configuración](#instalación-y-configuración)
- [Variables de entorno](#variables-de-entorno)
- [Modelos de datos](#modelos-de-datos)
- [Endpoints de la API](#endpoints-de-la-api)
- [Autenticación y roles (RBAC)](#autenticación-y-roles-rbac)
- [Procesamiento de Webhooks](#procesamiento-de-webhooks)
- [Cron Job — Expiración automática](#cron-job--expiración-automática)
- [Dispatcher de eventos (n8n / Zapier)](#dispatcher-de-eventos-n8n--zapier)
- [Bots de scraping — Validación de acceso](#bots-de-scraping--validación-de-acceso)
- [Ejecución local](#ejecución-local)

---

## Stack tecnológico

| Componente | Librería / Versión |
|---|---|
| Framework web | FastAPI >= 0.115 |
| Servidor ASGI | Uvicorn (con standard extras) |
| ORM | SQLAlchemy >= 2.0 |
| Base de datos | PostgreSQL (driver: psycopg2-binary) |
| Validación | Pydantic >= 2.7 (con email-validator) |
| Autenticación | python-jose (JWT) + passlib (bcrypt) |
| Webhooks salientes | httpx (async) |
| Stripe | stripe >= 8.0 |
| Scheduler | APScheduler >= 3.10 |
| Entorno | python-dotenv |

---

## Estructura del proyecto

```
CRM_DMGlobal/
│
├── main.py                   # App FastAPI + lifespan APScheduler
├── database.py               # Engine SQLAlchemy + SessionLocal + get_db
├── models.py                 # Modelos ORM: Cliente, Servicio, Suscripcion, AuditLog, Usuario
├── schemas.py                # Esquemas Pydantic de validación (entrada/salida)
├── auth.py                   # JWT, bcrypt, dependencias de rol (RBAC)
├── notifier.py               # Dispatcher HTTP saliente → n8n / Zapier
│
├── routers/
│   ├── clientes.py           # CRUD de Clientes  (/clientes)
│   ├── servicios.py          # CRUD de Servicios (/api/v1/servicios)
│   ├── webhooks.py           # Ingesta de webhooks MP y Stripe (/webhooks)
│   ├── validacion.py         # Validación de acceso para bots (/api/v1/validar-acceso)
│   └── login.py              # Autenticación de usuarios internos (/api/v1/auth)
│
├── tasks/
│   └── renovacion.py         # Cron job diario: expiración automática de suscripciones
│
├── bots/
│   ├── bot_guard.py          # Módulo reutilizable de validación para bots externos
│   ├── ejemplo_bot.py        # Ejemplos de integración (4 patrones)
│   └── .env.example          # Plantilla de variables de entorno para bots
│
└── requirements.txt
```

---

## Instalación y configuración

```bash
# 1. Clonar el repositorio
git clone <repo-url>
cd CRM_DMGlobal

# 2. Crear entorno virtual
python -m venv .venv
source .venv/bin/activate        # Linux / Mac
.venv\Scripts\activate           # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env con los valores reales

# 5. Levantar el servidor
uvicorn main:app --reload
```

Documentación interactiva disponible en:
- Swagger UI: `http://localhost:8000/docs`
- Redoc: `http://localhost:8000/redoc`

---

## Variables de entorno

Crear un archivo `.env` en la raíz del proyecto:

```env
# ── Base de datos ──────────────────────────────────────────────────────────
DATABASE_URL=postgresql+psycopg2://usuario:contraseña@localhost:5432/dmglobal

# ── JWT (usuarios internos) ────────────────────────────────────────────────
# Generar con: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY=cambiar_por_clave_segura_de_minimo_32_caracteres
JWT_EXPIRY_MINUTES=480          # 8 horas (default)

# ── MercadoPago ────────────────────────────────────────────────────────────
MP_ACCESS_TOKEN=APP_USR-...
MP_WEBHOOK_SECRET=...           # Secret del panel de MP para verificar firmas

# ── Stripe ─────────────────────────────────────────────────────────────────
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...

# ── Notificaciones salientes (n8n / Zapier) ────────────────────────────────
# URLs separadas por coma — puede ser una o varias
OUTGOING_WEBHOOK_URLS=https://n8n.dmglobal.com/webhook/crm,https://hooks.zapier.com/hooks/catch/123/abc

# ── Bots de scraping ───────────────────────────────────────────────────────
# Generar con: python -c "import secrets; print(secrets.token_hex(32))"
BOT_API_KEY=cambiar_por_token_secreto
```

---

## Modelos de datos

### `Cliente`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id` | BigInteger | PK, autoincrement |
| `razon_social` | String(255) | NOT NULL |
| `cuit_cuil` | String(20) | NOT NULL, UNIQUE, INDEX |
| `email_contacto` | String(254) | nullable |
| `telefono` | String(50) | nullable |
| `estado_general` | Enum | `activo` \| `inactivo` |
| `created_at` | DateTime(tz) | default UTC now |

### `Servicio`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id` | BigInteger | PK, autoincrement |
| `nombre` | String(255) | NOT NULL |
| `descripcion` | Text | nullable |
| `precio_base` | Float | NOT NULL, > 0 |
| `tipo_ejecucion` | Enum | `mensual` \| `por_ejecucion` \| `anual` |
| `activo` | Boolean | default True (soft delete) |

### `Suscripcion`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id` | BigInteger | PK, autoincrement |
| `cliente_id` | FK → Cliente | CASCADE delete |
| `servicio_id` | FK → Servicio | RESTRICT delete |
| `precio_acordado` | Float | nullable (hereda `precio_base` si es NULL) |
| `estado_suscripcion` | Enum | `activa` \| `pausada` \| `desactivada` |
| `pasarela_pago` | Enum | `mercadopago` \| `stripe` \| `manual` |
| `externa_id` | String(255) | nullable — ID de la suscripción en la pasarela |
| `fecha_inicio` | DateTime(tz) | default UTC now |
| `fecha_proxima_renovacion` | DateTime(tz) | nullable |
| `fecha_ultima_pausa` | DateTime(tz) | nullable |

> **Precio heredado:** si `precio_acordado` se crea como `None`, el event listener `before_insert` lo copia automáticamente desde `Servicio.precio_base`.

### `AuditLog`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id` | BigInteger | PK |
| `suscripcion_id` | FK → Suscripcion | SET NULL on delete, nullable |
| `usuario_interno` | String(255) | NOT NULL — usuario o sistema que originó el cambio |
| `accion` | String(100) | NOT NULL |
| `detalles` | Text | nullable |
| `timestamp` | DateTime(tz) | default UTC now |

### `Usuario`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id` | BigInteger | PK |
| `username` | String(100) | NOT NULL, UNIQUE |
| `email` | String(254) | NOT NULL, UNIQUE |
| `hashed_password` | String(255) | NOT NULL (bcrypt) |
| `rol` | Enum | `admin` \| `soporte` |
| `activo` | Boolean | default True |
| `created_at` | DateTime(tz) | default UTC now |

---

## Endpoints de la API

### Health check

```
GET /health
```
No requiere autenticación. Retorna `{"status": "ok"}`.

---

### Clientes — `/clientes`

> Requiere JWT con rol `admin` o `soporte`.

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/clientes/` | Listar clientes (paginado, filtro por estado) |
| `GET` | `/clientes/{id}` | Obtener cliente por ID — 404 si no existe |
| `POST` | `/clientes/` | Crear cliente — 409 si CUIT/CUIL duplicado |
| `PATCH` | `/clientes/{id}` | Actualización parcial |
| `DELETE` | `/clientes/{id}` | Eliminar cliente (hard delete) |

**Validaciones Pydantic:**
- `cuit_cuil`: solo dígitos, 10 u 11 caracteres (regex `^\d{10,11}$`)
- `email_contacto`: formato RFC-5322 via `EmailStr`

---

### Servicios — `/api/v1/servicios`

> `GET` requiere `admin` o `soporte`. Escritura requiere `admin`.

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| `GET` | `/api/v1/servicios/` | admin + soporte | Listar servicios activos (default) |
| `GET` | `/api/v1/servicios/{id}` | admin + soporte | Detalle de servicio — 404 si no existe |
| `POST` | `/api/v1/servicios/` | admin | Crear servicio — 409 si nombre duplicado |
| `PUT` | `/api/v1/servicios/{id}` | admin | Actualizar (parcial) — valida nombre único |
| `DELETE` | `/api/v1/servicios/{id}` | admin | **Soft delete** — pone `activo=False` |

**Validaciones:**
- `precio_base` debe ser **estrictamente mayor a cero**
- `tipo_ejecucion`: `mensual` | `por_ejecucion` | `anual`
- El `DELETE` es lógico (no borra la fila) para preservar el historial de suscripciones

---

### Autenticación — `/api/v1/auth`

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| `POST` | `/api/v1/auth/login` | público | Login → retorna JWT Bearer |
| `POST` | `/api/v1/auth/usuarios` | admin | Crear usuario interno |
| `GET` | `/api/v1/auth/usuarios` | admin | Listar usuarios internos |

**Request de login** (`application/x-www-form-urlencoded`):
```
username=admin&password=mi_contraseña
```

**Response:**
```json
{ "access_token": "eyJhbGci...", "token_type": "bearer" }
```

Usar el token en endpoints protegidos:
```
Authorization: Bearer eyJhbGci...
```

---

### Webhooks de pasarelas — `/webhooks`

> Endpoints públicos consumidos por MercadoPago y Stripe. Verifican firma criptográfica.

| Método | Ruta | Pasarela |
|---|---|---|
| `POST` | `/webhooks/mercadopago` | MercadoPago IPN / Webhook |
| `POST` | `/webhooks/stripe` | Stripe Events |

**MercadoPago — eventos procesados:**

| `type` | `status` en MP | Estado resultante |
|---|---|---|
| `subscription_preapproval` | `authorized` | `activa` |
| `subscription_preapproval` | `paused` | `pausada` |
| `subscription_preapproval` | `cancelled` | `pausada` |

**Stripe — eventos procesados:**

| Evento Stripe | `status` | Estado resultante |
|---|---|---|
| `customer.subscription.updated` | `active` | `activa` |
| `customer.subscription.updated` | `past_due` / `unpaid` / `canceled` | `pausada` |
| `customer.subscription.deleted` | (cualquiera) | `desactivada` |

Ambos endpoints siempre responden `HTTP 200` para evitar reintentos de la pasarela ante errores de negocio. Solo retornan `401` por firma inválida y `400` por JSON malformado.

---

### Validación de acceso para bots — `/api/v1/validar-acceso`

```
GET /api/v1/validar-acceso?cuit=20123456789&nombre_servicio=Monitoreo+Web
Headers: X-API-Key: <BOT_API_KEY>
```

**Respuestas:**

```json
{ "autorizado": true,  "estado": "activa" }
{ "autorizado": false, "estado": "pausada" }
{ "autorizado": false, "estado": "desactivada" }
{ "autorizado": false, "estado": "no_encontrada" }
```

- `401` si `X-API-Key` es inválida o no viene
- `200` en todos los casos de negocio (el bot lee `autorizado`)

---

## Autenticación y roles (RBAC)

### Flujo de autenticación

```
1. POST /api/v1/auth/login  →  JWT (8h por defecto)
2. Cada request protegido incluye:  Authorization: Bearer <token>
3. FastAPI valida firma + expiración + usuario activo en DB
4. La dependencia de rol verifica admin / soporte
```

### Matriz de permisos

| Recurso | admin | soporte |
|---|---|---|
| Leer clientes | ✅ | ✅ |
| Modificar clientes | ✅ | ❌ |
| Leer servicios | ✅ | ✅ |
| Crear / editar / eliminar servicios | ✅ | ❌ |
| Gestionar usuarios | ✅ | ❌ |
| Ver audit logs | ✅ | ✅ |

### Crear el primer usuario admin

```python
# Ejecutar en una sesión Python / script de seed
from database import SessionLocal
from auth import hash_password
from models import Usuario

db = SessionLocal()
db.add(Usuario(
    username="admin",
    email="admin@dmglobal.com",
    hashed_password=hash_password("contraseña_segura"),
    rol="admin",
))
db.commit()
db.close()
```

---

## Procesamiento de Webhooks

### MercadoPago

1. MP envía `POST /webhooks/mercadopago` con `type` y `data.id`
2. El endpoint verifica la firma HMAC-SHA256 del header `x-signature`
3. Llama a `GET https://api.mercadopago.com/preapproval/{id}` para obtener el estado completo
4. Extrae el CUIT desde el campo `external_reference` (lo llenamos al crear la suscripción en MP)
5. Actualiza `estado_suscripcion` en la DB + registra en `AuditLog`
6. Dispara notificación saliente en background (n8n/Zapier)

**Variable de entorno requerida en MercadoPago:**
Al crear la preaprobación, configurar `external_reference` con el CUIT del cliente.

### Stripe

1. Stripe envía `POST /webhooks/stripe` con el evento completo
2. El SDK de Stripe verifica `stripe-signature` (HMAC + anti-replay de timestamp)
3. Para `customer.subscription.updated` y `customer.subscription.deleted`
4. Extrae el CUIT desde `subscription.metadata.cuit_cuil`
5. Actualiza estado + AuditLog + notificación en background

**Variable de entorno requerida en Stripe:**
Al crear la suscripción en Stripe, agregar en `metadata`:
```python
stripe.Subscription.create(
    customer=customer_id,
    items=[...],
    metadata={"cuit_cuil": "20123456789"},
)
```

---

## Cron Job — Expiración automática

Corre diariamente a las **03:00 ART** vía APScheduler (AsyncIOScheduler), integrado en el lifespan de FastAPI.

**Lógica:**

```
SELECT suscripciones WHERE estado = 'activa' AND fecha_proxima_renovacion <= NOW()
    → Para cada una:
        UPDATE estado_suscripcion = 'pausada'
        UPDATE fecha_ultima_pausa = NOW()
        INSERT AuditLog (accion='expiracion_automatica', usuario_interno='sistema:cron')
    → COMMIT
    → Notificar n8n/Zapier por cada suscripción procesada
```

**Tolerancia a downtime:** `misfire_grace_time=3600` — si el servidor estuvo caído durante las 3:00 AM, el job corre igualmente hasta 1 hora después.

**Por qué APScheduler y no Celery:**
Celery requiere un broker externo (Redis/RabbitMQ) y procesos worker separados. Para un único job diario, APScheduler corre dentro del mismo proceso FastAPI sin infraestructura adicional.

---

## Dispatcher de eventos (n8n / Zapier)

El módulo `notifier.py` envía un `HTTP POST` a cada URL configurada en `OUTGOING_WEBHOOK_URLS` cada vez que una suscripción cambia de estado (por webhook de pasarela, por cron, o por acción manual).

**Payload enviado:**

```json
{
  "cuit": "20123456789",
  "nombre_servicio": "Monitoreo Web",
  "nuevo_estado": "pausada",
  "pasarela": "mercadopago",
  "suscripcion_id": 42,
  "timestamp": "2026-06-29T03:00:00+00:00"
}
```

- Ejecuta en `BackgroundTask` de FastAPI — no bloquea la respuesta al webhook
- Captura errores de red por URL (HTTPStatusError, HTTPError) sin propagar la excepción
- Soporta múltiples destinos simultáneos separados por coma

---

## Bots de scraping — Validación de acceso

El módulo `bots/bot_guard.py` es un wrapper reutilizable que verifica la suscripción **antes de abrir navegadores, proxies o consumir recursos**.

### Integración mínima (una línea)

```python
from bot_guard import verificar_licencia_dm_global

verificar_licencia_dm_global(CUIT_CLIENTE, "Monitoreo Web")
# Si no está autorizado → imprime mensaje y llama sys.exit(0)
# Si está autorizado → continúa normalmente

browser = playwright.chromium.launch(...)  # nunca llega aquí si está pausado
```

### Patrones disponibles

```python
# A — Decorador (recomendado)
@requiere_suscripcion_activa(cuit=CUIT, nombre_servicio="Monitoreo Web")
def ejecutar(): ...

# B — Imperativo con lectura del estado
autorizado, estado = validar_acceso(cuit=CUIT, nombre_servicio="Monitoreo Web")
if not autorizado:
    sys.exit(1)

# C — Async (Playwright async API)
@requiere_suscripcion_activa(cuit=CUIT, nombre_servicio="Monitoreo Web")
async def ejecutar(): ...

# D — Multi-cliente en loop
for cliente in CLIENTES:
    autorizado, estado = validar_acceso(**cliente)
    if not autorizado:
        continue  # salta al siguiente cliente
```

### Variables de entorno para bots

```env
DMGLOBAL_API_URL=https://api.dmglobal.com
DMGLOBAL_BOT_API_KEY=<mismo valor que BOT_API_KEY del servidor>
DMGLOBAL_TIMEOUT=8
CUIT_CLIENTE=20123456789
```

---

## Ejecución local

```bash
# Servidor de desarrollo
uvicorn main:app --reload --port 8000

# Verificar que el scheduler está corriendo
# (ver logs al iniciar: "APScheduler iniciado | renovación diaria a las 03:00 ART")

# Ejecutar el cron manualmente para testing
python -c "
import asyncio
from tasks.renovacion import verificar_renovaciones_vencidas
asyncio.run(verificar_renovaciones_vencidas())
"

# Generar un hash de contraseña para crear usuarios
python -c "from auth import hash_password; print(hash_password('mi_contraseña'))"
```
