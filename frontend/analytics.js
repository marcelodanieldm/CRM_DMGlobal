/**
 * analytics.js — Tablero de Comando de Servicios · DM Global
 *
 * Requiere auth-guard.js cargado antes (valida rol admin).
 *
 * Flujo:
 *  1. Verificar que el usuario es admin vía window.SESSION.
 *  2. Fetch al endpoint de salud → renderizar tarjetas en el grid.
 *  3. Click en "Exportar CSV" → descarga autenticada vía fetch + Blob.
 */

'use strict';

// ── Guardia de rol — auth-guard.js ya redirigió si no hay sesión ──────────────
// Esta verificación es una segunda capa para páginas admin-only.
if (window.SESSION && !window.SESSION.esAdmin) {
  // auth-guard.js ya debería haberlo manejado; esta línea es un fallback.
  window.location.replace('index.html');
}

// ── Formato ───────────────────────────────────────────────────────────────────

const fmt = {
  currency: (n) =>
    new Intl.NumberFormat('es-AR', {
      style: 'currency', currency: 'ARS', maximumFractionDigits: 0,
    }).format(n),

  number: (n) => new Intl.NumberFormat('es-AR').format(n),
};

// ── Fetch autenticado ─────────────────────────────────────────────────────────

async function apiFetch(path, options = {}) {
  const token = localStorage.getItem('dmg_token');
  const res = await fetch(`${CONFIG.API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers ?? {}),
    },
  });
  if (res.status === 401) { localStorage.clear(); window.location.replace('login.html'); }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Error ${res.status}`);
  }
  return res.json();
}

// ── Skeleton de carga ─────────────────────────────────────────────────────────

function mostrarSkeletons(n = 3) {
  const grid = document.getElementById('grid-skeleton');
  grid.innerHTML = Array.from({ length: n }, () => `
    <div class="bg-white border border-gray-200 rounded-lg p-6 animate-pulse">
      <div class="h-6 bg-gray-100 rounded w-3/4 mb-6"></div>
      <div class="space-y-3 mb-6">
        <div class="h-3 bg-gray-100 rounded w-1/3"></div>
        <div class="grid grid-cols-2 gap-4">
          <div class="h-8 bg-gray-100 rounded"></div>
          <div class="h-8 bg-gray-100 rounded"></div>
        </div>
      </div>
      <div class="h-3 bg-gray-100 rounded w-1/2 mb-4"></div>
      <div class="h-9 bg-gray-100 rounded"></div>
    </div>
  `).join('');
  grid.classList.remove('hidden');
}

function ocultarSkeletons() {
  const grid = document.getElementById('grid-skeleton');
  grid.classList.add('hidden');
  grid.innerHTML = '';
}

// ── Renderizado de tarjetas ───────────────────────────────────────────────────

/**
 * Construye y retorna el nodo DOM de una tarjeta de servicio.
 *
 * @param {object} s  Objeto ServicioSaludRead de la API.
 * @param {number} delay  Delay de animación en ms para efecto escalonado.
 */
function crearTarjeta(s, delay = 0) {
  const dotColor  = s.tasa_exito_promedio >= 95 ? 'bg-green-400' : 'bg-amber-400';
  const dotLabel  = s.tasa_exito_promedio >= 95 ? 'text-green-600' : 'text-amber-600';

  const card = document.createElement('div');
  card.className = 'card-service bg-white border border-gray-200 rounded-lg p-6 flex flex-col';
  card.style.animationDelay = `${delay}ms`;

  card.innerHTML = `
    <!-- Nombre del servicio -->
    <h2 class="font-light text-xl text-gray-950 leading-snug mb-6">${s.nombre_servicio}</h2>

    <!-- Métricas de negocio -->
    <div class="mb-5">
      <p class="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3">
        Métricas de negocio
      </p>
      <div class="grid grid-cols-2 gap-x-6 gap-y-4">

        <div>
          <p class="text-[11px] text-gray-400 font-light mb-1">Suscripciones activas</p>
          <p class="text-2xl font-semibold text-gray-900 tabular-nums">
            ${fmt.number(s.clientes_activos)}
          </p>
        </div>

        <div>
          <p class="text-[11px] text-gray-400 font-light mb-1">Ingreso mensual (MRR)</p>
          <p class="text-lg font-semibold text-gray-900 tabular-nums leading-tight">
            ${fmt.currency(s.mrr_generado)}
          </p>
        </div>

      </div>
    </div>

    <!-- Divisor -->
    <div class="border-t border-gray-100 mb-5"></div>

    <!-- Métricas técnicas -->
    <div class="mb-6">
      <p class="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3">
        Métricas técnicas
      </p>
      <div class="flex items-center gap-2.5">
        <span class="w-2 h-2 rounded-full ${dotColor} shrink-0"></span>
        <span class="text-xs text-gray-500 font-light">Tasa de éxito del bot</span>
        <span class="ml-auto text-sm font-semibold ${dotLabel} tabular-nums">
          ${s.tasa_exito_promedio}%
        </span>
      </div>
    </div>

    <!-- Botón exportar — siempre al pie de la tarjeta -->
    <div class="mt-auto">
      <button
        class="btn-export w-full py-2.5 flex items-center justify-center gap-2 text-xs text-gray-500 font-medium border border-gray-200 rounded-lg"
        data-action="exportar-csv"
        data-servicio-id="${s.id}"
        data-nombre-servicio="${s.nombre_servicio}">
        <svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round"
            d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"/>
        </svg>
        Exportar datos (.CSV)
      </button>
    </div>
  `;

  return card;
}

function renderGrid(servicios) {
  const grid = document.getElementById('grid-servicios');
  grid.innerHTML = '';

  if (servicios.length === 0) {
    grid.classList.add('hidden');
    document.getElementById('estado-vacio').classList.remove('hidden');
    return;
  }

  servicios.forEach((s, i) => {
    grid.appendChild(crearTarjeta(s, i * 60)); // 60 ms entre tarjeta
  });

  grid.classList.remove('hidden');
  document.getElementById('estado-vacio').classList.add('hidden');
}

// ── Exportación CSV con fetch autenticado ─────────────────────────────────────

/**
 * Descarga el CSV usando fetch con el header de autorización.
 * Más seguro que un simple <a href="..."> porque incluye el JWT.
 *
 * @param {number} servicioId
 * @param {string} nombreServicio  Para el feedback del botón.
 * @param {HTMLButtonElement} btnEl  Referencia al botón que disparó el evento.
 */
async function exportarCSV(servicioId, nombreServicio, btnEl) {
  const textoOriginal = btnEl.innerHTML;
  btnEl.disabled   = true;
  btnEl.innerHTML  = `
    <svg class="w-3.5 h-3.5 animate-spin shrink-0" fill="none" viewBox="0 0 24 24">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
    </svg>
    Generando CSV...
  `;

  try {
    const token = localStorage.getItem('dmg_token');
    const res = await fetch(
      `${CONFIG.API_BASE_URL}/analytics/servicios/${servicioId}/exportar`,
      { headers: { Authorization: `Bearer ${token}` } }
    );

    if (!res.ok) throw new Error(`Error ${res.status}`);

    // Convertir la respuesta a Blob y disparar la descarga en el navegador
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);

    const anchor    = document.createElement('a');
    anchor.href     = url;
    // El servidor ya envía el nombre en Content-Disposition; aquí como fallback
    anchor.download = `reporte_${nombreServicio.replace(/\s+/g, '_')}_${servicioId}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);

    URL.revokeObjectURL(url);
  } catch (err) {
    alert(`No se pudo generar el CSV: ${err.message}`);
  } finally {
    btnEl.disabled  = false;
    btnEl.innerHTML = textoOriginal;
  }
}

// ── Carga principal ───────────────────────────────────────────────────────────

async function cargarSalud() {
  document.getElementById('estado-error').classList.add('hidden');
  mostrarSkeletons(3);

  const btnRefresh = document.getElementById('btn-refresh');
  const iconRefresh = document.getElementById('refresh-icon');
  btnRefresh.disabled = true;
  iconRefresh.classList.add('animate-spin');

  try {
    const servicios = await apiFetch('/analytics/servicios/salud');
    ocultarSkeletons();
    renderGrid(servicios);

    // Subtítulo con timestamp de última actualización
    const ahora = new Intl.DateTimeFormat('es-AR', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    }).format(new Date());
    document.getElementById('header-subtitle').textContent =
      `Última actualización: ${ahora}`;

  } catch (err) {
    ocultarSkeletons();
    document.getElementById('estado-error').classList.remove('hidden');
    document.getElementById('error-msg').textContent =
      `Error al cargar métricas: ${err.message}`;
  } finally {
    btnRefresh.disabled = false;
    iconRefresh.classList.remove('animate-spin');
  }
}

// ── Delegación de eventos ─────────────────────────────────────────────────────

document.getElementById('grid-servicios').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-action="exportar-csv"]');
  if (!btn || btn.disabled) return;

  const servicioId     = parseInt(btn.dataset.servicioId, 10);
  const nombreServicio = btn.dataset.nombreServicio;
  exportarCSV(servicioId, nombreServicio, btn);
});

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {

  // Poblar sidebar con datos de sesión
  if (window.SESSION) {
    document.getElementById('sidebar-username').textContent = SESSION.username;
    document.getElementById('sidebar-avatar').textContent   = SESSION.username.charAt(0).toUpperCase();
  }

  // Cargar datos
  cargarSalud();

  // Botón actualizar
  document.getElementById('btn-refresh').addEventListener('click', cargarSalud);

  // Logout
  document.getElementById('logout-btn').addEventListener('click', () => {
    localStorage.clear();
    window.location.replace('login.html');
  });

});
