# CRM DMGlobal

API interna y panel web para la gestión de clientes, servicios y suscripciones de DM Global. Controla el acceso de bots de scraping, sincroniza estados de pago con MercadoPago y Stripe, y dispara eventos automáticos hacia n8n/Zapier.

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
- [Frontend — Panel de administración](#frontend--panel-de-administración)
- [Ejecución local](#ejecución-local)

---

## Stack tecnológico

### Backend

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

### Frontend

| Componente | Tecnología |
|---|---|
| Markup | HTML5 semántico, sin bundler |
| Estilos | Tailwind CSS (CDN) |
| Tipografía | Inter (Google Fonts) |
| Lógica | JavaScript Vanilla (ES2021, módulos IIFE) |
| HTTP | Fetch API nativa con JWT Bearer |
| Auth | localStorage + RBAC por rol en cada pantalla |

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
│   ├── suscripciones.py      # CRUD de Suscripciones (/api/v1/suscripciones)
│   ├── analytics.py          # Métricas del dashboard (/api/v1/analytics)
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
├── frontend/                 # Panel web de administración (archivos estáticos)
│   ├── config.js             # URL base de la API y configuración global
│   ├── auth-guard.js         # Middleware de sesión y control de roles
│   ├── index.html            # Dashboard principal (SPA ligero)
│   ├── dashboard.js          # Métricas, navegación y lógica del dashboard
│   ├── login.html            # Pantalla de login
│   ├── login.js              # Flujo OAuth2 → JWT → localStorage
│   ├── cliente.html          # Ficha detalle de un cliente
│   ├── cliente.js            # Datos del cliente, suscripciones y auditoría
│   ├── servicios.html        # Catálogo de servicios (CRUD completo)
│   ├── servicios.js          # Lógica CRUD del catálogo con panel slide-over
│   ├── usuarios.html         # Gestión de operadores internos (solo admin)
│   ├── usuarios.js           # Alta y listado de usuarios del sistema
│   ├── analytics.html        # Tablero de analítica por servicio
│   └── analytics.js          # Gráficos y métricas de suscripciones
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

# 5. Inicializar la base de datos con datos de prueba (solo dev)
python setup_dev.py

# 6. Levantar el servidor
uvicorn main:app --reload
```

Documentación interactiva disponible en:
- Swagger UI: `http://localhost:8000/docs`
- Redoc: `http://localhost:8000/redoc`
- Panel web: `http://localhost:8000/frontend/index.html` (o abrir directamente en el navegador)

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
| `nombre` | String(255) | NOT NULL, UNIQUE por negocio |
| `descripcion` | Text | nullable |
| `precio_base` | Float | NOT NULL, > 0 |
| `tipo_ejecucion` | Enum | `mensual` \| `por_ejecucion` \| `anual` |
| `tipo_servicio` | Enum | `automatizacion` \| `bot` \| `scraping` \| `servicio_comun` |
| `activo` | Boolean | default `True` (soft delete) |

> **`tipo_servicio`** clasifica la infraestructura interna que activa cada servicio. Los scripts de Python, n8n y Zapier leen este campo para saber qué tecnología deben encender: clúster de navegadores para `scraping` / `bot`, flujos de APIs para `automatizacion`, o ninguna automatización técnica para `servicio_comun`.

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
| `GET` | `/api/v1/servicios/` | admin + soporte | Listar servicios (activos por defecto, `?solo_activos=false` para todos) |
| `GET` | `/api/v1/servicios/{id}` | admin + soporte | Detalle de servicio — 404 si no existe |
| `POST` | `/api/v1/servicios/` | admin | Crear servicio — 409 si nombre duplicado |
| `PUT` | `/api/v1/servicios/{id}` | admin | Actualizar (parcial) — valida nombre único |
| `DELETE` | `/api/v1/servicios/{id}` | admin | **Soft delete** — pone `activo=False` |

**Validaciones:**
- `precio_base` debe ser **estrictamente mayor a cero**
- `tipo_ejecucion`: `mensual` | `por_ejecucion` | `anual`
- `tipo_servicio`: `automatizacion` | `bot` | `scraping` | `servicio_comun`
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

## Frontend — Panel de administración

El panel es un conjunto de archivos HTML/JS/CSS estáticos ubicados en `frontend/`. No requiere bundler ni servidor de desarrollo propio: se sirven directamente desde FastAPI o cualquier servidor estático, y se comunican con el backend vía Fetch API con JWT.

### Diseño

- Fondo blanco dominante (`bg-white`) con superficie de página en `bg-gray-50`
- Sidebar fijo de 240 px con marca, navegación y footer de sesión
- Bordes grises finos (`border-gray-200`) sin sombras agresivas
- Tipografía Inter en pesos 300 / 400 / 500 / 600
- Tailwind CSS vía CDN (sin purge — apto para paneles internos de baja escala)

### Archivos y responsabilidades

#### `config.js`

Configuración global del frontend. **Debe cargarse primero en todos los HTML.**

```js
const CONFIG = {
  API_BASE_URL: 'http://localhost:8000/api/v1',  // cambiar en producción
  BOT_API_KEY:  '',
  ENTORNO:      'desarrollo',  // 'desarrollo' | 'produccion'
};
```

| Variable | Uso |
|---|---|
| `API_BASE_URL` | Prefijo de todos los `fetch` al backend |
| `BOT_API_KEY` | Clave para el endpoint `/validar-acceso` si se llama desde el panel |
| `ENTORNO` | En `desarrollo` habilita fallbacks a datos mock si la API no responde |

---

#### `auth-guard.js`

Middleware de seguridad que **debe cargarse en segundo lugar**, antes de cualquier script de negocio. Protege todas las pantallas internas.

**Comportamiento al cargar:**

1. Si no hay token en `localStorage` → redirige a `login.html` de inmediato (sin flash de contenido).
2. Con sesión válida → expone `window.SESSION` con token y datos del usuario.
3. Página marcada como solo-admin + rol soporte → reemplaza el contenido por pantalla de acceso denegado.
4. Oculta automáticamente todos los elementos `[data-requiere-admin]` si el rol es `soporte`.

**`window.SESSION` expuesto:**

```js
SESSION.token      // JWT Bearer
SESSION.user       // objeto completo del usuario
SESSION.rol        // 'admin' | 'soporte'
SESSION.username   // string
SESSION.esAdmin    // boolean
```

**Páginas registradas como solo-admin:** `usuarios.html`

---

#### `login.html` + `login.js`

Pantalla de autenticación. Si ya existe una sesión activa, redirige a `index.html` sin mostrar el formulario.

**Flujo:**
1. `POST /api/v1/auth/login` con `application/x-www-form-urlencoded`
2. El JWT recibido se decodifica en el cliente (sin verificar firma — eso lo hace el servidor en cada request)
3. Se persisten `dmg_token` y `dmg_user` en `localStorage`
4. Redirección a `index.html`

---

#### `index.html` + `dashboard.js`

Dashboard principal. SPA ligero con 4 secciones navegables por el sidebar: **Dashboard**, **Clientes** (placeholder), **Catálogo de Servicios** (enlaza a `servicios.html`) y **Auditoría / Logs** (placeholder).

**Sección Dashboard muestra:**
- Tarjetas de métricas: Total Clientes, Suscripciones Activas, Pausadas, Ingresos Proyectados
- Tabla de últimos movimientos (audit logs con estado, acción, pasarela y fecha)

**Navegación SPA:** el listener de clicks en `.nav-link` intercepta solo los links con `href="#"`. Los links a páginas reales (como `servicios.html`) se dejan pasar al navegador.

**Carga de datos:** `GET /api/v1/analytics/resumen` para métricas, `GET /api/v1/analytics/movimientos` para la tabla.

---

#### `cliente.html` + `cliente.js`

Ficha detalle de un cliente, accesible vía `cliente.html?id={clienteId}`.

**Secciones:**

| Sección | Contenido |
|---|---|
| Datos del cliente | Razón social, CUIT/CUIL, email, teléfono, estado, fecha de alta |
| Servicios y automatizaciones | Tabla de suscripciones activas con precio, pasarela, estado y fecha de renovación |
| Historial de auditoría | Acordeón colapsable con todos los AuditLog vinculados al cliente |

**Acciones disponibles:**
- **Asignar nuevo servicio** → modal con selector de servicio, precio acordado y pasarela de pago (`POST /api/v1/suscripciones/`)
- **Pausar / Reactivar / Desactivar** suscripción → `PATCH /api/v1/suscripciones/{id}`

**Control de rol:** el botón "Asignar nuevo servicio" lleva `data-requiere-admin` y queda oculto para el rol `soporte`.

---

#### `servicios.html` + `servicios.js`

Gestión completa del catálogo de servicios de DM Global. Accessible desde el sidebar de cualquier pantalla.

**Tabla del catálogo** — columnas:

| Columna | Detalle |
|---|---|
| Servicio | Nombre técnico + descripción truncada |
| Tipo | Badge de color según `tipo_servicio` |
| Modalidad | Mensual / Anual / Por ejecución |
| Precio base | Formateado en ARS con `Intl.NumberFormat` |
| Estado | Badge verde Activo / gris Inactivo |
| Acciones | Editar + Inactivar (solo admin) |

**Panel slide-over** (derecha de la pantalla, 440 px):
- Se abre al hacer clic en "Crear Nuevo Servicio" o "Editar"
- Campos: Nombre técnico, Descripción, Precio base, Modalidad, Tipo de servicio, toggle Activo/Inactivo
- Validación client-side antes del fetch; errores de la API mostrados inline en el panel
- Se cierra con el botón X, Escape, o clic en el backdrop

**Tipos de servicio y su significado operativo:**

| Valor | Label | Color | Infra que activa |
|---|---|---|---|
| `automatizacion` | Automatización | Azul cielo | Flujos n8n / Zapier entre APIs |
| `bot` | Bot | Violeta | Scripts de notificación o scraping liviano |
| `scraping` | Scraping | Ámbar | Clúster de navegadores Playwright / Selenium |
| `servicio_comun` | Servicio Común | Gris | Sin automatización técnica (servicio manual) |

**Control de rol:**
- `data-requiere-admin` en el botón "Crear Nuevo Servicio" → oculto para `soporte`
- Los botones Editar e Inactivar en la tabla se renderizan solo si `SESSION.esAdmin === true`
- El rol `soporte` puede ver el catálogo completo (activos e inactivos) pero no modificarlo

**Endpoints consumidos:**

```
GET  /api/v1/servicios/?solo_activos=false&limit=200   → poblar tabla
POST /api/v1/servicios/                                → crear servicio
PUT  /api/v1/servicios/{id}                            → editar servicio
DEL  /api/v1/servicios/{id}                            → inactivar (soft delete)
```

---

#### `usuarios.html` + `usuarios.js`

Gestión de operadores internos del CRM. **Acceso exclusivo para admin** (auth-guard redirige a soporte si intenta acceder).

**Funcionalidades:**
- Tabla de usuarios con username, email, rol y estado
- Modal para registrar nuevo operador (username, email, contraseña, rol)
- `POST /api/v1/auth/usuarios` para crear, `GET /api/v1/auth/usuarios` para listar

---

#### `analytics.html` + `analytics.js`

Tablero de analítica desglosado por servicio. Muestra distribución de suscripciones, ingresos por servicio y tendencias.

**Endpoints consumidos:** `GET /api/v1/analytics/*`

---

### Orden de carga de scripts (obligatorio)

Todos los HTML internos (excepto `login.html`) deben cargar los scripts en este orden:

```html
<script src="config.js"></script>      <!-- 1. Configuración global -->
<script src="auth-guard.js"></script>  <!-- 2. Protección de sesión y roles -->
<script src="[pagina].js"></script>    <!-- 3. Lógica de negocio de la pantalla -->
```

### Control de acceso visual por rol

| Mecanismo | Uso |
|---|---|
| `data-requiere-admin` en el HTML | auth-guard oculta el elemento si el rol es `soporte` |
| `SESSION.esAdmin` en el JS | Guards en renderizado dinámico (filas de tabla, botones inline) |
| `PAGINAS_SOLO_ADMIN` en auth-guard | Redirige y muestra pantalla de "Acceso denegado" para páginas enteras |

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

# Re-crear la base de datos de desarrollo (SQLite)
# Eliminar el archivo .db existente y luego:
python setup_dev.py
```

### Usuarios de prueba (setup_dev.py)

| Usuario | Contraseña | Rol |
|---|---|---|
| `admin` | `Admin123` | admin |
| `soporte` | `Soporte123` | soporte |
