/**
 * cliente.js — Ficha única del cliente · CRM DMGlobal
 *
 * Renderiza dinámicamente tres secciones:
 *  1. Datos del cliente
 *  2. Tabla de suscripciones/automatizaciones con acciones
 *  3. Acordeón <details> con historial de auditoría
 *
 * La página lee ?id=<clienteId> de la URL.
 * Las llamadas API usan el token JWT guardado por index.html.
 * Si la API no responde, se usan los datos mock de este archivo.
 */

'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// RBAC — Control de acceso basado en roles (capa visual)
//
// IMPORTANTE: estas restricciones son solo de interfaz (UX guard).
// La autorización definitiva reside en el backend (auth.py → require_admin).
// Un usuario con DevTools puede bypassear esta capa; el backend siempre
// valida el rol antes de ejecutar cualquier cambio persistente.
//
// En producción, reemplazar este objeto con los datos reales del JWT:
//   const usuarioActual = Auth.getUser();  // { username, rol }
// ─────────────────────────────────────────────────────────────────────────────

const usuarioActual = {
  role: (typeof SESSION !== 'undefined' && SESSION.esAdmin) ? 'admin' : 'soporte',
};

/**
 * Deshabilita visualmente el botón "Asignar nuevo servicio".
 * Aplica: disabled, opacity-40, cursor-not-allowed, pointer-events-none.
 * El atributo title informa al usuario el motivo de la restricción.
 */
function restringirBotonAsignar() {
  const btn = document.getElementById('btn-asignar-servicio');
  if (!btn) return;
  btn.disabled = true;
  btn.classList.add('opacity-40', 'cursor-not-allowed', 'pointer-events-none');
  btn.setAttribute('title', 'Acción restringida — requiere rol Administrador');
}

/**
 * Restaura el botón "Asignar nuevo servicio" al estado habilitado (admin).
 */
function habilitarBotonAsignar() {
  const btn = document.getElementById('btn-asignar-servicio');
  if (!btn) return;
  btn.disabled = false;
  btn.classList.remove('opacity-40', 'cursor-not-allowed', 'pointer-events-none');
  btn.removeAttribute('title');
}

/**
 * Recorre el DOM y oculta con `hidden` todos los botones [Dar de baja].
 * Usa el selector data-action="dar_de_baja" para identificarlos sin
 * depender de texto visible (tolerante a cambios de etiqueta).
 * Debe llamarse tras cada operación que modifique la tabla.
 */
function ocultarBotonesBaraja() {
  document.querySelectorAll('[data-action="dar_de_baja"]').forEach((btn) => {
    btn.classList.add('hidden');
  });
}

/**
 * Punto de entrada principal del sistema de permisos.
 * Evalúa usuarioActual.role y aplica o elimina restricciones en el DOM.
 *
 * Reglas:
 *   admin   → acceso completo, sin restricciones
 *   soporte → sin poder asignar servicios ni dar de baja;
 *             puede Activar y Pausar para resolver incidencias técnicas
 */
function aplicarRBAC() {
  if (usuarioActual.role === 'admin') {
    habilitarBotonAsignar();
    return; // admin: todos los controles habilitados
  }

  // soporte (o rol desconocido) → restricciones máximas
  restringirBotonAsignar();
  ocultarBotonesBaraja();
}

// Verificar que config.js fue cargado antes que este script
if (typeof CONFIG === 'undefined') {
  throw new Error('config.js debe cargarse antes que cliente.js');
}

// ─────────────────────────────────────────────────────────────────────────────
// AUTH
// ─────────────────────────────────────────────────────────────────────────────

const Auth = {
  getToken() { return localStorage.getItem('dmg_token'); },
  isAuthenticated() { return !!this.getToken(); },
};

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
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Error ${res.status}`);
  }
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// MOCK DATA — pobla las tablas al cargar la página
// ─────────────────────────────────────────────────────────────────────────────

const MOCK_CLIENTE = {
  id: 1,
  razon_social:    'Constructora Andina S.A.',
  cuit_cuil:       '30-71234567-9',
  email_contacto:  'administracion@constructoraandina.com',
  telefono:        '+54 11 4444-5555',
  estado_general:  'activo',
  created_at:      '2024-03-15T10:00:00Z',
};

const MOCK_SUSCRIPCIONES = [
  {
    id: 1,
    servicio_id:          1,
    servicio_nombre:      'Monitoreo Web',
    tipo_ejecucion:       'mensual',
    precio_base:          150_000,
    precio_acordado:      125_000,   // precio combinado (difiere del base)
    estado_suscripcion:   'activa',
    pasarela_pago:        'stripe',
    externa_id:           'sub_1AbCd2EfGh',
    fecha_inicio:         '2024-03-15T10:00:00Z',
    fecha_proxima_renovacion: '2026-07-15T10:00:00Z',
  },
  {
    id: 2,
    servicio_id:          2,
    servicio_nombre:      'Scraping de Precios',
    tipo_ejecucion:       'mensual',
    precio_base:          95_000,
    precio_acordado:      95_000,    // igual al base — sin nota de combinado
    estado_suscripcion:   'pausada',
    pasarela_pago:        'mercadopago',
    externa_id:           '2c938084726fca48',
    fecha_inicio:         '2024-06-01T00:00:00Z',
    fecha_proxima_renovacion: '2026-06-29T03:00:00Z',
  },
  {
    id: 3,
    servicio_id:          3,
    servicio_nombre:      'Reportes Automáticos',
    tipo_ejecucion:       'anual',
    precio_base:          800_000,
    precio_acordado:      680_000,   // precio combinado
    estado_suscripcion:   'activa',
    pasarela_pago:        'manual',
    externa_id:           null,
    fecha_inicio:         '2025-01-01T00:00:00Z',
    fecha_proxima_renovacion: '2027-01-01T00:00:00Z',
  },
];

// Servicios disponibles para asignar (catálogo)
const MOCK_SERVICIOS_DISPONIBLES = [
  { id: 4, nombre: 'Auditoría de Competencia', precio_base: 120_000, tipo_ejecucion: 'mensual' },
  { id: 5, nombre: 'Alertas de Stock',          precio_base: 60_000,  tipo_ejecucion: 'mensual' },
  { id: 6, nombre: 'Dashboard Personalizado',   precio_base: 350_000, tipo_ejecucion: 'anual'   },
];

const MOCK_AUDIT = [
  {
    timestamp:       '2026-06-29T03:00:14Z',
    usuario_interno: 'sistema:cron',
    accion:          'expiracion_automatica',
    detalles:        'renovacion_vencida=2026-06-29 cuit=30-71234567-9 servicio=Scraping de Precios',
  },
  {
    timestamp:       '2026-06-20T14:22:05Z',
    usuario_interno: 'webhook:stripe',
    accion:          'estado:pausada→activa',
    detalles:        'event_type=customer.subscription.updated stripe_status=active sub_id=sub_1AbCd2EfGh',
  },
  {
    timestamp:       '2026-06-18T09:11:33Z',
    usuario_interno: 'admin',
    accion:          'estado:activa→pausada',
    detalles:        'Solicitud manual del cliente — esperando confirmación de pago',
  },
  {
    timestamp:       '2026-05-15T10:00:00Z',
    usuario_interno: 'admin',
    accion:          'nueva_suscripcion',
    detalles:        'servicio=Reportes Automáticos precio_acordado=680000 pasarela=manual',
  },
  {
    timestamp:       '2026-04-01T08:30:00Z',
    usuario_interno: 'webhook:mercadopago',
    accion:          'estado:activa→pausada',
    detalles:        'type=subscription_preapproval mp_status=paused sub_id=2c938084726fca48',
  },
  {
    timestamp:       '2024-06-01T00:00:00Z',
    usuario_interno: 'admin',
    accion:          'nueva_suscripcion',
    detalles:        'servicio=Scraping de Precios precio_acordado=95000 pasarela=mercadopago',
  },
  {
    timestamp:       '2024-03-15T10:00:00Z',
    usuario_interno: 'admin',
    accion:          'nueva_suscripcion',
    detalles:        'servicio=Monitoreo Web precio_acordado=125000 pasarela=stripe (precio_combinado)',
  },
];

// Estado mutable en memoria (simula el estado de la DB)
let suscripciones = MOCK_SUSCRIPCIONES.map(s => ({ ...s }));

// ─────────────────────────────────────────────────────────────────────────────
// FORMATO
// ─────────────────────────────────────────────────────────────────────────────

const fmt = {
  currency: (n) =>
    new Intl.NumberFormat('es-AR', { style: 'currency', currency: 'ARS', maximumFractionDigits: 0 }).format(n),

  date: (iso) =>
    new Intl.DateTimeFormat('es-AR', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    }).format(new Date(iso)),

  shortDate: (iso) =>
    new Intl.DateTimeFormat('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(iso)),
};

// ─────────────────────────────────────────────────────────────────────────────
// BADGES
// ─────────────────────────────────────────────────────────────────────────────

const ESTADO_CLS = {
  activa:      'text-green-700  bg-green-50  ring-green-600/20',
  pausada:     'text-amber-700  bg-amber-50  ring-amber-600/20',
  desactivada: 'text-gray-500   bg-gray-100  ring-gray-500/20',
  activo:      'text-green-700  bg-green-50  ring-green-600/20',
  inactivo:    'text-gray-500   bg-gray-100  ring-gray-500/20',
};

function badge(text, extra = '') {
  const cls = ESTADO_CLS[text] ?? 'text-gray-600 bg-gray-100 ring-gray-500/20';
  return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ring-1 ring-inset ${cls} ${extra}">${text}</span>`;
}

const PASARELA_DOT = {
  stripe:      'bg-violet-400',
  mercadopago: 'bg-sky-400',
  manual:      'bg-gray-400',
};

function pasarelaDot(p) {
  const dot = PASARELA_DOT[p] ?? 'bg-gray-300';
  const label = { stripe: 'Stripe', mercadopago: 'MercadoPago', manual: 'Manual' }[p] ?? p;
  return `<span class="inline-flex items-center gap-1.5 text-xs text-gray-500">
    <span class="w-1.5 h-1.5 rounded-full ${dot} shrink-0"></span>${label}
  </span>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// SECCIÓN 1 — Datos del cliente
// ─────────────────────────────────────────────────────────────────────────────

function renderCliente(c) {
  document.getElementById('breadcrumb-nombre').textContent = c.razon_social;
  document.title = `${c.razon_social} · DM Global`;

  document.getElementById('section-cliente').innerHTML = `
    <div class="flex items-start justify-between gap-6">

      <!-- Info principal -->
      <div class="space-y-3 min-w-0">
        <div class="flex items-center gap-3 flex-wrap">
          <h1 class="text-lg font-semibold text-gray-900 leading-tight">${c.razon_social}</h1>
          ${badge(c.estado_general)}
        </div>

        <p class="font-mono-custom text-sm text-gray-500 tracking-wider">${c.cuit_cuil}</p>

        <div class="flex flex-wrap items-center gap-x-6 gap-y-1.5 text-sm text-gray-500 font-light">
          ${c.email_contacto ? `
            <span class="flex items-center gap-1.5">
              <svg class="w-3.5 h-3.5 text-gray-300 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75"/>
              </svg>
              <a href="mailto:${c.email_contacto}" class="hover:text-gray-700 transition">${c.email_contacto}</a>
            </span>` : ''}
          ${c.telefono ? `
            <span class="flex items-center gap-1.5">
              <svg class="w-3.5 h-3.5 text-gray-300 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 6.75c0 8.284 6.716 15 15 15h2.25a2.25 2.25 0 002.25-2.25v-1.372c0-.516-.351-.966-.852-1.091l-4.423-1.106c-.44-.11-.902.055-1.173.417l-.97 1.293c-.282.376-.769.542-1.21.38a12.035 12.035 0 01-7.143-7.143c-.162-.441.004-.928.38-1.21l1.293-.97c.363-.271.527-.734.417-1.173L6.963 3.102a1.125 1.125 0 00-1.091-.852H4.5A2.25 2.25 0 002.25 4.5v2.25z"/>
              </svg>
              ${c.telefono}
            </span>` : ''}
        </div>
      </div>

      <!-- Meta -->
      <div class="text-right text-xs text-gray-400 font-light shrink-0 space-y-1">
        <p>ID interno: <span class="font-mono-custom text-gray-500">#${String(c.id).padStart(4, '0')}</span></p>
        <p>Alta: ${fmt.shortDate(c.created_at)}</p>
      </div>
    </div>
  `;
}

// ─────────────────────────────────────────────────────────────────────────────
// SECCIÓN 2 — Tabla de servicios / automatizaciones
// ─────────────────────────────────────────────────────────────────────────────

function renderServicios(lista) {
  const tbody = document.getElementById('tbody-servicios');
  tbody.innerHTML = '';

  if (lista.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" class="px-3 py-10 text-center text-sm text-gray-400">
          Este cliente no tiene servicios asignados.
        </td>
      </tr>`;
    aplicarRBAC(); // aplica restricciones al botón "Asignar" incluso sin filas
    return;
  }

  lista.forEach((sub) => {
    const tr = document.createElement('tr');
    tr.id = `row-sub-${sub.id}`;
    tr.className = 'hover:bg-gray-50/60 transition-colors';
    tr.innerHTML = buildServicioRow(sub);
    tbody.appendChild(tr);
  });

  // Aplicar RBAC después de que todos los botones estén en el DOM
  aplicarRBAC();
}

function buildServicioRow(sub) {
  const esPrecioCombinado = sub.precio_acordado !== sub.precio_base;
  const precioHTML = `
    <div>
      <span class="text-sm text-gray-900">${fmt.currency(sub.precio_acordado)}</span>
      ${esPrecioCombinado ? `
        <br>
        <em class="text-[10px] text-gray-400 not-italic font-light">
          Precio combinado · lista: ${fmt.currency(sub.precio_base)}
        </em>
        <em class="text-[10px] text-violet-400 ml-1">★</em>` : ''}
    </div>`;

  const renovacionHTML = sub.fecha_proxima_renovacion
    ? `<span class="text-xs text-gray-400 font-mono-custom">${fmt.shortDate(sub.fecha_proxima_renovacion)}</span>`
    : '<span class="text-xs text-gray-300">—</span>';

  return `
    <td class="px-3 py-4">
      <div class="text-sm font-medium text-gray-900">${sub.servicio_nombre}</div>
    </td>
    <td class="px-3 py-4">
      <span class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium text-gray-500 bg-gray-100 uppercase tracking-wide">
        ${sub.tipo_ejecucion}
      </span>
    </td>
    <td class="px-3 py-4">${precioHTML}</td>
    <td class="px-3 py-4">${pasarelaDot(sub.pasarela_pago)}</td>
    <td class="px-3 py-4">${badge(sub.estado_suscripcion)}</td>
    <td class="px-3 py-4">${renovacionHTML}</td>
    <td class="px-3 py-4">
      <div class="flex items-center justify-end gap-1.5" id="acciones-${sub.id}">
        ${buildAccionButtons(sub)}
      </div>
    </td>
  `;
}

function buildAccionButtons(sub) {
  // Los botones usan data-attributes exclusivamente — sin onclick inline.
  // Un único listener con delegación de eventos en tbody captura todos los clicks.
  const BTN = (text, accion, colorCls) => `
    <button
      class="px-2.5 py-1 text-xs border border-gray-200 rounded-lg ${colorCls} hover:opacity-80 transition-opacity whitespace-nowrap"
      data-action="${accion}"
      data-sub-id="${sub.id}">
      ${text}
    </button>`;

  if (sub.estado_suscripcion === 'desactivada') {
    return '<span class="text-xs text-gray-300">Dada de baja</span>';
  }

  const buttons = [];
  if (sub.estado_suscripcion === 'pausada')  buttons.push(BTN('Activar',    'activar',      'text-green-700'));
  if (sub.estado_suscripcion === 'activa')   buttons.push(BTN('Pausar',     'pausar',       'text-amber-700'));
  buttons.push(BTN('Dar de baja', 'dar_de_baja', 'text-red-600'));
  return buttons.join('');
}

// ─────────────────────────────────────────────────────────────────────────────
// SECCIÓN 2 — Acciones de suscripción
// ─────────────────────────────────────────────────────────────────────────────

const ACCION_MAP = {
  activar:      { nuevo_estado: 'activa',      msg: 'Suscripción activada correctamente.',    icon: '✓' },
  pausar:       { nuevo_estado: 'pausada',     msg: 'Suscripción pausada.',                   icon: '⏸' },
  dar_de_baja:  { nuevo_estado: 'desactivada', msg: 'Servicio dado de baja del cliente.',     icon: '✕' },
};

async function accionSuscripcion(subId, accion) {
  const cfg = ACCION_MAP[accion];
  if (!cfg) return;

  if (accion === 'dar_de_baja') {
    const sub = suscripciones.find(s => s.id === subId);
    const ok = window.confirm(
      `¿Confirmar baja del servicio "${sub?.servicio_nombre ?? ''}"?\n` +
      `Esta acción pasará el estado a "desactivada".`
    );
    if (!ok) return;
  }

  // Deshabilitar botones de la fila mientras procesa
  const botonesContainer = document.getElementById(`acciones-${subId}`);
  if (botonesContainer) {
    botonesContainer.querySelectorAll('button').forEach(b => { b.disabled = true; b.style.opacity = '0.4'; });
  }

  try {
    // Llamada real a la API; fallback a actualización local si no responde
    let subActualizada = null;
    try {
      subActualizada = await actualizarEstadoSuscripcion(subId, cfg.nuevo_estado);
    } catch (apiErr) {
      // API no disponible (dev sin backend): continuar con actualización local
      console.warn(`API no disponible, actualizando solo en memoria: ${apiErr.message}`);
    }

    // Actualizar estado en memoria con datos de la API o con el estado esperado
    const idx = suscripciones.findIndex(s => s.id === subId);
    if (idx !== -1) {
      suscripciones[idx] = subActualizada
        ? { ...suscripciones[idx], ...subActualizada }
        : { ...suscripciones[idx], estado_suscripcion: cfg.nuevo_estado };

      // Re-renderizar solo la fila afectada
      const tr = document.getElementById(`row-sub-${subId}`);
      if (tr) {
        tr.innerHTML = buildServicioRow(suscripciones[idx]);
        // La fila recién pintada tiene botones frescos; re-aplicar permisos
        ocultarBotonesBaraja();
      }
    }

    // Agregar entrada al log de auditoría en memoria
    const nuevaEntrada = {
      timestamp:       new Date().toISOString(),
      usuario_interno: `${usuarioActual.role} (panel)`,
      accion:          `estado→${cfg.nuevo_estado}`,
      detalles:        `sub_id=${subId} servicio=${suscripciones[idx]?.servicio_nombre}`,
    };
    const tbody = document.getElementById('tbody-auditoria');
    if (tbody) {
      const tr = document.createElement('tr');
      tr.className = 'border-t border-gray-50 bg-yellow-50/40';
      tr.innerHTML = buildAuditRow(nuevaEntrada);
      tbody.prepend(tr);
      actualizarContadorAudit();
      // Abrir el acordeón si estaba cerrado
      document.getElementById('section-auditoria').open = true;
    }

    showToast(cfg.icon, cfg.msg);
  } catch (err) {
    showToast('✕', `Error: ${err.message}`);
    // Restaurar botones
    if (botonesContainer) {
      botonesContainer.querySelectorAll('button').forEach(b => { b.disabled = false; b.style.opacity = ''; });
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// SECCIÓN 3 — Historial de auditoría
// ─────────────────────────────────────────────────────────────────────────────

function renderAuditoria(logs) {
  const tbody = document.getElementById('tbody-auditoria');
  tbody.innerHTML = '';

  logs.forEach((log) => {
    const tr = document.createElement('tr');
    tr.className = 'border-t border-gray-50 hover:bg-gray-50/40 transition-colors';
    tr.innerHTML = buildAuditRow(log);
    tbody.appendChild(tr);
  });

  actualizarContadorAudit();
}

function buildAuditRow(log) {
  const accionCls = log.accion.includes('activa')       ? 'text-green-600'
    : log.accion.includes('pausada')                    ? 'text-amber-600'
    : log.accion.includes('desactivada')                ? 'text-red-500'
    : log.accion === 'expiracion_automatica'            ? 'text-orange-500'
    : log.accion.includes('nueva_suscripcion')          ? 'text-blue-500'
    : 'text-gray-500';

  return `
    <td class="py-2.5 pr-6 text-gray-400 whitespace-nowrap align-top">${fmt.date(log.timestamp)}</td>
    <td class="py-2.5 pr-6 text-gray-500 whitespace-nowrap align-top">${log.usuario_interno}</td>
    <td class="py-2.5 pr-6 whitespace-nowrap align-top">
      <span class="${accionCls} font-medium">${log.accion}</span>
    </td>
    <td class="py-2.5 text-gray-400 break-all">${log.detalles}</td>
  `;
}

function actualizarContadorAudit() {
  const rows = document.getElementById('tbody-auditoria')?.querySelectorAll('tr').length ?? 0;
  const el = document.getElementById('audit-count');
  if (el) el.textContent = `${rows} registro${rows !== 1 ? 's' : ''}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// MODAL — Asignar nuevo servicio
// ─────────────────────────────────────────────────────────────────────────────

function openModal(serviciosDisponibles) {
  const select = document.getElementById('modal-servicio');
  select.innerHTML = '<option value="">Seleccionar servicio...</option>';

  serviciosDisponibles.forEach(s => {
    const opt = document.createElement('option');
    opt.value   = s.id;
    opt.dataset.precioBase = s.precio_base;
    opt.dataset.tipo       = s.tipo_ejecucion;
    opt.textContent = `${s.nombre} — ${fmt.currency(s.precio_base)} / ${s.tipo_ejecucion}`;
    select.appendChild(opt);
  });

  document.getElementById('modal-error').classList.add('hidden');
  document.getElementById('modal-precio-acordado').value = '';
  document.getElementById('modal-precio-base-row').classList.add('hidden');
  document.getElementById('modal-asignar').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal-asignar').classList.add('hidden');
}

async function confirmarAsignar() {
  const selectEl   = document.getElementById('modal-servicio');
  const errorEl    = document.getElementById('modal-error');
  const confirmBtn = document.getElementById('modal-confirm-btn');

  const servicioId = parseInt(selectEl.value, 10);
  if (!servicioId) {
    errorEl.textContent = 'Seleccioná un servicio.';
    errorEl.classList.remove('hidden');
    return;
  }

  const opt           = selectEl.querySelector(`option[value="${servicioId}"]`);
  const precioBase    = parseFloat(opt.dataset.precioBase);
  const precioRaw     = document.getElementById('modal-precio-acordado').value;
  const precioAcordado = precioRaw ? parseFloat(precioRaw) : null;
  const pasarela      = document.getElementById('modal-pasarela').value;
  const servicio      = MOCK_SERVICIOS_DISPONIBLES.find(s => s.id === servicioId);

  if (precioAcordado !== null && precioAcordado <= 0) {
    errorEl.textContent = 'El precio acordado debe ser mayor a cero.';
    errorEl.classList.remove('hidden');
    return;
  }

  errorEl.classList.add('hidden');
  confirmBtn.disabled   = true;
  confirmBtn.textContent = 'Asignando...';

  try {
    let nuevaSub = null;
    try {
      nuevaSub = await apiFetch('/suscripciones/', {
        method: 'POST',
        body: JSON.stringify({
          cliente_id: clienteId,
          servicio_id: servicioId,
          precio_acordado: precioAcordado,
          pasarela_pago: pasarela,
        }),
      });
    } catch (apiErr) {
      console.warn(`API no disponible para crear suscripción: ${apiErr.message}`);
    }

    // Si la API respondió, usar los datos reales; sino construir un objeto local
    const subLocal = nuevaSub ?? {
      id:                      Date.now(),
      servicio_id:             servicioId,
      servicio_nombre:         servicio?.nombre ?? 'Nuevo servicio',
      tipo_ejecucion:          servicio?.tipo_ejecucion ?? 'mensual',
      precio_base:             precioBase,
      precio_acordado:         precioAcordado ?? precioBase,
      estado_suscripcion:      'activa',
      pasarela_pago:           pasarela,
      externa_id:              null,
      fecha_inicio:            new Date().toISOString(),
      fecha_proxima_renovacion: null,
    };
    suscripciones.push(subLocal);
    renderServicios(suscripciones);

    closeModal();
    showToast('✓', `Servicio "${subLocal.servicio_nombre}" asignado correctamente.`);
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
  } finally {
    confirmBtn.disabled   = false;
    confirmBtn.textContent = 'Asignar servicio';
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// TOAST de confirmación
// ─────────────────────────────────────────────────────────────────────────────

let toastTimer = null;

function showToast(icon, msg) {
  const toast   = document.getElementById('toast');
  const iconEl  = document.getElementById('toast-icon');
  const msgEl   = document.getElementById('toast-msg');

  iconEl.textContent = icon;
  msgEl.textContent  = msg;
  toast.classList.remove('hide');

  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add('hide'), 3500);
}

// ─────────────────────────────────────────────────────────────────────────────
// FETCH API — Funciones de red nativas (async/await)
// ─────────────────────────────────────────────────────────────────────────────

const clienteId = parseInt(new URLSearchParams(location.search).get('id') ?? '1', 10);

/**
 * Carga el perfil del cliente y sus suscripciones activas desde FastAPI.
 * Realiza dos GETs en paralelo y inyecta el resultado en las tablas del DOM.
 * Fallback a datos mock si la API no responde (modo desarrollo).
 *
 * @param {number} id  ID del cliente a cargar.
 */
async function cargarDatosCliente(id) {
  const [clienteRes, subsRes] = await Promise.allSettled([
    apiFetch(`/clientes/${id}`),
    apiFetch(`/suscripciones/?cliente_id=${id}`),
  ]);

  const cliente = clienteRes.status === 'fulfilled'
    ? clienteRes.value
    : (console.warn('No se pudo cargar el cliente desde la API — usando mock'), MOCK_CLIENTE);

  suscripciones = subsRes.status === 'fulfilled'
    ? subsRes.value
    : (console.warn('No se pudo cargar suscripciones — usando mock'), MOCK_SUSCRIPCIONES.map(s => ({ ...s })));

  renderCliente(cliente);
  renderServicios(suscripciones);
  renderAuditoria(MOCK_AUDIT); // TODO: reemplazar con GET /api/v1/audit-logs?suscripcion_id=...
}

/**
 * Envía un PUT a /suscripciones/{id}/estado con el nuevo estado técnico.
 * Al recibir HTTP 200 actualiza el badge visual y prepend al historial de auditoría.
 * Si el backend devuelve 403 (soporte intentando dar de baja), propaga el error.
 *
 * @param {number} suscripcionId  ID de la suscripción a modificar.
 * @param {string} nuevoEstado    'activa' | 'pausada' | 'desactivada'
 * @returns {Promise<object>}     SuscripcionRead actualizado devuelto por la API.
 */
async function actualizarEstadoSuscripcion(suscripcionId, nuevoEstado) {
  return apiFetch(`/suscripciones/${suscripcionId}/estado`, {
    method: 'PUT',
    body: JSON.stringify({ estado: nuevoEstado }),
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────────────
// ALIASES PÚBLICOS — nombres canónicos de los prompts de diseño
//
// Los nombres internos (camelCase corto) se usan dentro del script.
// Estos aliases los exponen con los nombres documentados externamente.
// ─────────────────────────────────────────────────────────────────────────────

const renderizarSuscripciones = renderServicios;
const renderizarAuditLogs     = renderAuditoria;
const abrirModal              = openModal;
const cerrarModal             = closeModal;

// ─────────────────────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {

  cargarDatosCliente(clienteId);

  // ── Delegación de eventos — tabla de servicios ────────────────────────────
  // Un único listener sobre el tbody captura clicks en cualquier botón de acción,
  // incluyendo los de filas agregadas dinámicamente (nuevas suscripciones).
  document.getElementById('tbody-servicios').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-action][data-sub-id]');
    if (!btn || btn.disabled) return;

    const subId = parseInt(btn.dataset.subId, 10);
    const accion = btn.dataset.action;

    // Verificar RBAC antes de procesar (doble seguridad visual)
    if (accion === 'dar_de_baja' && usuarioActual.role !== 'admin') return;

    accionSuscripcion(subId, accion);
  });

  // Botón "Asignar nuevo servicio"
  document.getElementById('btn-asignar-servicio').addEventListener('click', () => {
    abrirModal(MOCK_SERVICIOS_DISPONIBLES);
  });

  // Cerrar modal
  document.getElementById('modal-close-btn').addEventListener('click',  closeModal);
  document.getElementById('modal-cancel-btn').addEventListener('click', closeModal);
  document.getElementById('modal-asignar').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
  });

  // Confirmar asignación
  document.getElementById('modal-confirm-btn').addEventListener('click', confirmarAsignar);

  // Actualizar precio base al seleccionar servicio
  document.getElementById('modal-servicio').addEventListener('change', (e) => {
    const opt    = e.target.options[e.target.selectedIndex];
    const precio = opt.dataset.precioBase;
    const row    = document.getElementById('modal-precio-base-row');
    const label  = document.getElementById('modal-precio-base-label');

    if (precio) {
      label.textContent = fmt.currency(parseFloat(precio));
      row.classList.remove('hidden');
    } else {
      row.classList.add('hidden');
    }
  });

  // Cerrar modal con Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
  });

  // ── Sección de Servicios Premium ─────────────────────────────────────────
  cargarServiciosPremium(clienteId);

  document.getElementById('btn-guardar-feedback').addEventListener('click', () => {
    guardarFeedbackConfig(clienteId);
  });

  document.getElementById('btn-guardar-recepcionista').addEventListener('click', () => {
    guardarRecepcionistaConfig(clienteId);
  });

  // Solo admins pueden guardar configuraciones premium
  if (usuarioActual.role !== 'admin') {
    document.getElementById('btn-guardar-feedback').disabled = true;
    document.getElementById('btn-guardar-recepcionista').disabled = true;
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// SERVICIOS PREMIUM — carga y guardado
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Carga la configuración de ambos servicios premium del cliente y rellena los inputs.
 * @param {number} clienteId
 */
async function cargarServiciosPremium(clienteId) {
  const token = localStorage.getItem('dmglobal_token');
  try {
    const res = await fetch(
      `${CONFIG.API_BASE_URL}/clientes/${clienteId}/servicios-premium`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    if (!res.ok) return;
    const data = await res.json();

    // ── Feedback ────────────────────────────────────────────────────────────
    if (data.feedback) {
      const fb = data.feedback;
      document.getElementById('fb-tipo-negocio').value = fb.tipo_negocio || 'HOTEL';
      document.getElementById('fb-review-link').value  = fb.google_review_link || '';
      document.getElementById('fb-sheet-url').value    = fb.google_sheet_url   || '';
      document.getElementById('fb-activo').checked     = fb.activo;
      actualizarBadge('badge-feedback', true, fb.google_review_link);
    }

    // ── Recepcionista ───────────────────────────────────────────────────────
    if (data.recepcionista) {
      const rec = data.recepcionista;
      document.getElementById('rec-hotel-id').value       = rec.hotel_id                 || '';
      document.getElementById('rec-wa-phone-id').value    = rec.whatsapp_phone_number_id || '';
      document.getElementById('rec-sheets-id').value      = rec.google_sheets_id         || '';
      document.getElementById('rec-drive-id').value       = rec.google_drive_file_id     || '';
      document.getElementById('rec-precheckin-url').value = rec.precheckin_form_url      || '';
      document.getElementById('rec-activo').checked       = rec.activo;
      const operativo = !!(rec.hotel_id && rec.whatsapp_phone_number_id && rec.google_sheets_id && rec.google_drive_file_id);
      actualizarBadge('badge-recepcionista', true, operativo);
    }
  } catch (_) {
    // Si la API no responde, los inputs quedan vacíos (modo desarrollo)
  }
}

/**
 * Actualiza el badge de estado de una tarjeta premium.
 * @param {string} badgeId   — ID del elemento span del badge
 * @param {boolean} existe   — si ya hay configuración guardada
 * @param {string|boolean} completo — campo clave para considerar "operativo"
 */
function actualizarBadge(badgeId, existe, completo) {
  const badge = document.getElementById(badgeId);
  if (!badge) return;
  if (!existe) {
    badge.textContent = 'Sin configurar';
    badge.className   = 'text-[10px] font-medium px-2 py-0.5 rounded-full bg-gray-100 text-gray-400';
    return;
  }
  if (completo) {
    badge.textContent = 'Operativo';
    badge.className   = 'text-[10px] font-medium px-2 py-0.5 rounded-full bg-green-100 text-green-700';
  } else {
    badge.textContent = 'Incompleto';
    badge.className   = 'text-[10px] font-medium px-2 py-0.5 rounded-full bg-amber-100 text-amber-700';
  }
}

/**
 * Muestra un mensaje de resultado debajo del botón de guardado.
 * @param {string} msgId   — ID del <p> de mensaje
 * @param {boolean} ok     — true = éxito, false = error
 * @param {string} texto   — texto a mostrar
 */
function mostrarMsgPremium(msgId, ok, texto) {
  const el = document.getElementById(msgId);
  if (!el) return;
  el.textContent = texto;
  el.className   = `text-xs text-center mt-2 ${ok ? 'text-green-600' : 'text-red-500'}`;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 4000);
}

/**
 * Guarda (upsert) la configuración del Servicio de Feedback para el cliente.
 * @param {number} clienteId
 */
async function guardarFeedbackConfig(clienteId) {
  const btn   = document.getElementById('btn-guardar-feedback');
  const token = localStorage.getItem('dmglobal_token');

  btn.disabled    = true;
  btn.textContent = 'Guardando...';

  const payload = {
    tipo_negocio:       document.getElementById('fb-tipo-negocio').value,
    google_review_link: document.getElementById('fb-review-link').value.trim() || null,
    google_sheet_url:   document.getElementById('fb-sheet-url').value.trim()   || null,
    activo:             document.getElementById('fb-activo').checked,
  };

  try {
    const res = await fetch(
      `${CONFIG.API_BASE_URL}/clientes/${clienteId}/feedback-config`,
      {
        method:  'PUT',
        headers: {
          Authorization:  `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      }
    );

    if (res.ok) {
      mostrarMsgPremium('feedback-msg', true, 'Configuracion guardada correctamente');
      actualizarBadge('badge-feedback', true, payload.google_review_link);
    } else {
      const err = await res.json().catch(() => ({}));
      mostrarMsgPremium('feedback-msg', false, err.detail || 'Error al guardar');
    }
  } catch (_) {
    mostrarMsgPremium('feedback-msg', false, 'Sin conexion con el servidor');
  } finally {
    btn.disabled    = (usuarioActual.role !== 'admin');
    btn.textContent = 'Guardar configuracion';
  }
}

/**
 * Guarda (upsert) la configuración del Recepcionista Virtual para el cliente.
 * @param {number} clienteId
 */
async function guardarRecepcionistaConfig(clienteId) {
  const btn   = document.getElementById('btn-guardar-recepcionista');
  const token = localStorage.getItem('dmglobal_token');

  btn.disabled    = true;
  btn.textContent = 'Guardando...';

  const payload = {
    hotel_id:                 document.getElementById('rec-hotel-id').value.trim().toUpperCase() || null,
    whatsapp_phone_number_id: document.getElementById('rec-wa-phone-id').value.trim()             || null,
    google_sheets_id:         document.getElementById('rec-sheets-id').value.trim()               || null,
    google_drive_file_id:     document.getElementById('rec-drive-id').value.trim()                || null,
    precheckin_form_url:      document.getElementById('rec-precheckin-url').value.trim()          || null,
    activo:                   document.getElementById('rec-activo').checked,
  };

  try {
    const res = await fetch(
      `${CONFIG.API_BASE_URL}/clientes/${clienteId}/recepcionista-config`,
      {
        method:  'PUT',
        headers: {
          Authorization:  `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      }
    );

    if (res.ok) {
      mostrarMsgPremium('recepcionista-msg', true, 'Configuracion guardada correctamente');
      const operativo = !!(payload.hotel_id && payload.whatsapp_phone_number_id &&
                           payload.google_sheets_id && payload.google_drive_file_id);
      actualizarBadge('badge-recepcionista', true, operativo);
    } else {
      const err = await res.json().catch(() => ({}));
      mostrarMsgPremium('recepcionista-msg', false, err.detail || 'Error al guardar');
    }
  } catch (_) {
    mostrarMsgPremium('recepcionista-msg', false, 'Sin conexion con el servidor');
  } finally {
    btn.disabled    = (usuarioActual.role !== 'admin');
    btn.textContent = 'Guardar configuracion';
  }
}
