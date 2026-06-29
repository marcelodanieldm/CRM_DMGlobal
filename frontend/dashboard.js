/**
 * dashboard.js — CRM DMGlobal
 *
 * Responsabilidades:
 *  - Autenticación JWT (login / logout / persistencia en localStorage)
 *  - Llamadas a la API FastAPI con manejo de errores
 *  - Renderizado dinámico de métricas y tabla de movimientos
 *  - Navegación entre secciones (SPA ligero)
 */

'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// CONFIGURACIÓN — lee de config.js (debe cargarse antes en el HTML)
// ─────────────────────────────────────────────────────────────────────────────

if (typeof CONFIG === 'undefined') {
  throw new Error('config.js debe cargarse antes que dashboard.js');
}

// ─────────────────────────────────────────────────────────────────────────────
// AUTH — token en localStorage
// ─────────────────────────────────────────────────────────────────────────────

const Auth = {
  TOKEN_KEY: 'dmg_token',
  USER_KEY:  'dmg_user',

  getToken()  { return localStorage.getItem(this.TOKEN_KEY); },
  getUser()   { return JSON.parse(localStorage.getItem(this.USER_KEY) || 'null'); },

  set(token, user) {
    localStorage.setItem(this.TOKEN_KEY, token);
    localStorage.setItem(this.USER_KEY, JSON.stringify(user));
  },

  clear() {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.USER_KEY);
  },

  isAuthenticated() { return !!this.getToken(); },
};

// ─────────────────────────────────────────────────────────────────────────────
// API — fetch con JWT y manejo centralizado de errores
// ─────────────────────────────────────────────────────────────────────────────

async function apiFetch(path, options = {}) {
  const token = Auth.getToken();
  const res = await fetch(`${CONFIG.API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers ?? {}),
    },
  });

  if (res.status === 401) {
    Auth.clear();
    showLogin();
    throw new Error('Sesión expirada');
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Error ${res.status}`);
  }

  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// LOGIN
// ─────────────────────────────────────────────────────────────────────────────

async function doLogin(username, password) {
  const body = new URLSearchParams({ username, password });
  const res = await fetch(`${CONFIG.API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  if (!res.ok) throw new Error('Usuario o contraseña incorrectos');

  const data = await res.json();

  // Decodificar payload del JWT para obtener username y rol (sin verificar firma)
  const [, payloadB64] = data.access_token.split('.');
  const payload = JSON.parse(atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/')));

  Auth.set(data.access_token, { username: payload.sub, rol: payload.rol });
}

// ─────────────────────────────────────────────────────────────────────────────
// UI — mostrar / ocultar vistas
// ─────────────────────────────────────────────────────────────────────────────

function showLogin() {
  document.getElementById('login-overlay').classList.remove('hidden');
  document.getElementById('app').classList.add('hidden');
}

function showApp() {
  document.getElementById('login-overlay').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');

  const user = Auth.getUser();
  if (user) {
    document.getElementById('sidebar-username').textContent = user.username;
    document.getElementById('sidebar-rol').textContent = user.rol === 'admin' ? 'Administrador' : 'Soporte';
    document.getElementById('sidebar-avatar').textContent = user.username.charAt(0).toUpperCase();
  }
}

function setPageTitle(title) {
  document.getElementById('page-title').textContent = title;
}

// ─────────────────────────────────────────────────────────────────────────────
// FORMATO — helpers de presentación
// ─────────────────────────────────────────────────────────────────────────────

const fmt = {
  currency: (n) =>
    new Intl.NumberFormat('es-AR', { style: 'currency', currency: 'ARS', maximumFractionDigits: 0 }).format(n),

  date: (iso) => {
    const d = new Date(iso);
    return new Intl.DateTimeFormat('es-AR', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    }).format(d);
  },

  relativeDate: (iso) => {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1)  return 'ahora mismo';
    if (m < 60) return `hace ${m} min`;
    const h = Math.floor(m / 60);
    if (h < 24) return `hace ${h} h`;
    const dias = Math.floor(h / 24);
    return `hace ${dias} día${dias > 1 ? 's' : ''}`;
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// BADGES — estado y pasarela
// ─────────────────────────────────────────────────────────────────────────────

const ESTADO_BADGE = {
  activa:       'text-green-700 bg-green-50 ring-1 ring-inset ring-green-600/20',
  pausada:      'text-amber-700 bg-amber-50 ring-1 ring-inset ring-amber-600/20',
  desactivada:  'text-gray-500 bg-gray-100 ring-1 ring-inset ring-gray-500/20',
};

const ACCION_BADGE = {
  'estado:pausada→activa':        'text-green-700 bg-green-50',
  'estado:activa→pausada':        'text-amber-700 bg-amber-50',
  'expiracion_automatica':        'text-orange-700 bg-orange-50',
  'estado:activa→desactivada':    'text-red-700 bg-red-50',
  'estado_sin_cambio:activa':     'text-blue-600 bg-blue-50',
};

const PASARELA_LABEL = {
  mercadopago:  { label: 'MercadoPago', dot: 'bg-sky-400' },
  stripe:       { label: 'Stripe',      dot: 'bg-violet-400' },
  manual:       { label: 'Manual',      dot: 'bg-gray-400' },
  'sistema:cron': { label: 'Cron',      dot: 'bg-orange-400' },
};

function estadoBadgeHTML(estado) {
  const cls = ESTADO_BADGE[estado] ?? 'text-gray-500 bg-gray-100';
  return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${cls}">${estado}</span>`;
}

function accionBadgeHTML(accion) {
  const cls = ACCION_BADGE[accion] ?? 'text-gray-600 bg-gray-100';
  const label = accion.replace(/estado:/g, '').replace(/_/g, ' ');
  return `<span class="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium ${cls} max-w-[160px] truncate" title="${accion}">${label}</span>`;
}

function pasarelaHTML(pasarela) {
  const p = PASARELA_LABEL[pasarela] ?? { label: pasarela, dot: 'bg-gray-300' };
  return `
    <span class="inline-flex items-center gap-1.5 text-xs text-gray-500">
      <span class="w-1.5 h-1.5 rounded-full ${p.dot} shrink-0"></span>
      ${p.label}
    </span>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// DATOS MOCK — para desarrollo sin backend o cuando faltan endpoints
// ─────────────────────────────────────────────────────────────────────────────

const MOCK_MOVIMIENTOS = [
  {
    cliente:   'Constructora Andina S.A.',
    cuit:      '30-71234567-9',
    servicio:  'Monitoreo Web',
    estado:    'activa',
    accion:    'estado:pausada→activa',
    pasarela:  'stripe',
    timestamp: new Date(Date.now() - 4 * 60000).toISOString(),
  },
  {
    cliente:   'Tech Solutions SRL',
    cuit:      '30-68912345-1',
    servicio:  'Scraping de Precios',
    estado:    'pausada',
    accion:    'estado:activa→pausada',
    pasarela:  'mercadopago',
    timestamp: new Date(Date.now() - 32 * 60000).toISOString(),
  },
  {
    cliente:   'Distribuidora Norte SA',
    cuit:      '20-23456789-4',
    servicio:  'Monitoreo Web',
    estado:    'pausada',
    accion:    'expiracion_automatica',
    pasarela:  'sistema:cron',
    timestamp: new Date(Date.now() - 3 * 3600000).toISOString(),
  },
  {
    cliente:   'Inversiones Del Sur',
    cuit:      '27-30123456-5',
    servicio:  'Reportes Automáticos',
    estado:    'activa',
    accion:    'estado:pausada→activa',
    pasarela:  'stripe',
    timestamp: new Date(Date.now() - 5 * 3600000).toISOString(),
  },
  {
    cliente:   'Grupo Medina Hnos.',
    cuit:      '30-70000001-2',
    servicio:  'Monitoreo Web',
    estado:    'pausada',
    accion:    'expiracion_automatica',
    pasarela:  'sistema:cron',
    timestamp: new Date(Date.now() - 22 * 3600000).toISOString(),
  },
  {
    cliente:   'Agro Export Corp.',
    cuit:      '30-60000002-8',
    servicio:  'Scraping de Precios',
    estado:    'desactivada',
    accion:    'estado:activa→desactivada',
    pasarela:  'stripe',
    timestamp: new Date(Date.now() - 26 * 3600000).toISOString(),
  },
  {
    cliente:   'Importadora Leal SRL',
    cuit:      '30-69000003-3',
    servicio:  'Reportes Automáticos',
    estado:    'activa',
    accion:    'estado_sin_cambio:activa',
    pasarela:  'mercadopago',
    timestamp: new Date(Date.now() - 48 * 3600000).toISOString(),
  },
];

const MOCK_METRICS = {
  totalClientes: 47,
  activas: 38,
  pausadas: 7,
  ingresos: 2_840_000,
};

// ─────────────────────────────────────────────────────────────────────────────
// RENDER — métricas
// ─────────────────────────────────────────────────────────────────────────────

function renderMetrics({ totalClientes, activas, pausadas, ingresos }) {
  document.getElementById('metric-total-clientes').textContent = totalClientes;
  document.getElementById('metric-activas').textContent        = activas;
  document.getElementById('metric-pausadas').textContent       = pausadas;
  document.getElementById('metric-ingresos').textContent       = fmt.currency(ingresos);
}

// ─────────────────────────────────────────────────────────────────────────────
// RENDER — tabla de movimientos (DOM nativo + template literals)
// ─────────────────────────────────────────────────────────────────────────────

function renderMovimientos(movimientos) {
  const tbody = document.getElementById('tbody-movimientos');

  // Limpiar estado de carga
  tbody.innerHTML = '';

  if (movimientos.length === 0) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td colspan="6" class="px-6 py-12 text-center text-sm text-gray-400">
        Sin movimientos recientes
      </td>`;
    tbody.appendChild(tr);
    return;
  }

  movimientos.forEach((item) => {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-gray-50/70 transition-colors cursor-default';

    tr.innerHTML = `
      <td class="px-6 py-3.5">
        <div class="text-sm font-medium text-gray-900 leading-tight">${item.cliente}</div>
        <div class="text-[11px] text-gray-400 font-light mt-0.5">${item.cuit}</div>
      </td>
      <td class="px-4 py-3.5">
        <span class="text-sm text-gray-600">${item.servicio}</span>
      </td>
      <td class="px-4 py-3.5">
        ${estadoBadgeHTML(item.estado)}
      </td>
      <td class="px-4 py-3.5">
        ${accionBadgeHTML(item.accion)}
      </td>
      <td class="px-4 py-3.5">
        ${pasarelaHTML(item.pasarela)}
      </td>
      <td class="px-4 py-3.5">
        <span class="text-[11px] text-gray-400" title="${fmt.date(item.timestamp)}">
          ${fmt.relativeDate(item.timestamp)}
        </span>
      </td>
    `;

    tbody.appendChild(tr);
  });

  // Actualizar contador
  document.getElementById('movimientos-count').textContent =
    `${movimientos.length} registro${movimientos.length !== 1 ? 's' : ''}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// CARGA DEL DASHBOARD — API real + fallback a mock
// ─────────────────────────────────────────────────────────────────────────────

async function loadDashboard() {
  setRefreshLoading(true);

  try {
    // Clientes: endpoint real disponible
    const clientes = await apiFetch('/clientes/?limit=200');  // → CONFIG.API_BASE_URL + /clientes/
    const totalClientes = clientes.length;
    const activos = clientes.filter(c => c.estado_general === 'activo').length;

    // Métricas de suscripciones: usar mock hasta que exista /api/v1/metrics
    // TODO: reemplazar por apiFetch('/api/v1/metrics') cuando esté disponible
    renderMetrics({
      totalClientes,
      activas:   MOCK_METRICS.activas,
      pausadas:  MOCK_METRICS.pausadas,
      ingresos:  MOCK_METRICS.ingresos,
    });

  } catch (err) {
    // Si la API no responde, usar mock completo
    console.warn('API no disponible, usando datos de ejemplo:', err.message);
    renderMetrics(MOCK_METRICS);
  }

  // Movimientos: usar mock hasta que exista el endpoint de audit logs
  // TODO: reemplazar por apiFetch('/api/v1/audit-logs?limit=50') cuando esté disponible
  renderMovimientos(MOCK_MOVIMIENTOS);

  setRefreshLoading(false);
}

function setRefreshLoading(isLoading) {
  const btn  = document.getElementById('refresh-btn');
  const icon = document.getElementById('refresh-icon');
  btn.disabled = isLoading;
  icon.classList.toggle('animate-spin', isLoading);
}

// ─────────────────────────────────────────────────────────────────────────────
// NAVEGACIÓN — SPA ligero entre secciones
// ─────────────────────────────────────────────────────────────────────────────

const SECTIONS = ['dashboard', 'clientes', 'servicios', 'auditoria'];

const PAGE_TITLES = {
  dashboard:  'Panel de control',
  clientes:   'Clientes',
  servicios:  'Catálogo de Servicios',
  auditoria:  'Auditoría / Logs',
};

function navigateTo(section) {
  // Actualizar active en sidebar
  document.querySelectorAll('.nav-link').forEach((link) => {
    const isActive = link.dataset.section === section;
    link.classList.toggle('active', isActive);
  });

  // Mostrar la sección correcta
  SECTIONS.forEach((s) => {
    const el = document.getElementById(`section-${s}`);
    if (el) el.classList.toggle('hidden', s !== section);
  });

  setPageTitle(PAGE_TITLES[section] ?? section);
}

// ─────────────────────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {

  // ── Fecha en el header ────────────────────────────────────────────────────
  const today = new Intl.DateTimeFormat('es-AR', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  }).format(new Date());
  document.getElementById('page-date').textContent =
    today.charAt(0).toUpperCase() + today.slice(1);

  // ── Mostrar vista inicial ─────────────────────────────────────────────────
  if (Auth.isAuthenticated()) {
    showApp();
    loadDashboard();
  } else {
    showLogin();
  }

  // ── Formulario de login ───────────────────────────────────────────────────
  document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const username   = document.getElementById('input-username').value.trim();
    const password   = document.getElementById('input-password').value;
    const btn        = document.getElementById('login-btn');
    const errorEl    = document.getElementById('login-error');

    errorEl.classList.add('hidden');
    btn.disabled     = true;
    btn.textContent  = 'Ingresando...';

    try {
      await doLogin(username, password);
      showApp();
      loadDashboard();
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.classList.remove('hidden');
      document.getElementById('input-password').value = '';
    } finally {
      btn.disabled    = false;
      btn.textContent = 'Ingresar';
    }
  });

  // ── Logout ────────────────────────────────────────────────────────────────
  document.getElementById('logout-btn').addEventListener('click', () => {
    Auth.clear();
    showLogin();
    document.getElementById('input-username').value = '';
    document.getElementById('input-password').value = '';
  });

  // ── Navegación sidebar ────────────────────────────────────────────────────
  document.querySelectorAll('.nav-link').forEach((link) => {
    link.addEventListener('click', (e) => {
      // Si el link apunta a otra página real, dejar navegar al browser.
      const href = link.getAttribute('href');
      if (href && href !== '#') return;
      e.preventDefault();
      navigateTo(link.dataset.section);
    });
  });

  // ── Botón de actualizar ───────────────────────────────────────────────────
  document.getElementById('refresh-btn').addEventListener('click', () => {
    if (Auth.isAuthenticated()) loadDashboard();
  });

});
