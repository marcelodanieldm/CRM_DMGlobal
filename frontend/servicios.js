'use strict';

// ─── Constantes de presentación ───────────────────────────────────────────────

const TIPO_LABELS = {
  automatizacion: 'Automatización',
  bot:            'Bot',
  scraping:       'Scraping',
  servicio_comun: 'Servicio Común',
};

const TIPO_BADGE = {
  automatizacion: 'bg-sky-50 text-sky-700',
  bot:            'bg-violet-50 text-violet-700',
  scraping:       'bg-amber-50 text-amber-700',
  servicio_comun: 'bg-gray-100 text-gray-600',
};

const MODALIDAD_LABELS = {
  mensual:       'Mensual',
  anual:         'Anual',
  por_ejecucion: 'Por ejecución',
};

// ─── Estado ───────────────────────────────────────────────────────────────────

let servicios = [];
let editandoId = null;

// ─── Inicialización ───────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  inicializarSidebar();
  inicializarPanel();
  inicializarFormulario();
  cargarServicios();
});

// ─── Sidebar y sesión ─────────────────────────────────────────────────────────

function inicializarSidebar() {
  const avatarEl   = document.getElementById('sidebar-avatar');
  const usernameEl = document.getElementById('sidebar-username');
  const rolEl      = document.getElementById('sidebar-rol');

  if (avatarEl)   avatarEl.textContent   = (SESSION.username?.[0] ?? 'U').toUpperCase();
  if (usernameEl) usernameEl.textContent = SESSION.username;
  if (rolEl)      rolEl.textContent      = SESSION.esAdmin ? 'Administrador' : 'Soporte';

  document.getElementById('logout-btn')?.addEventListener('click', () => {
    localStorage.clear();
    window.location.replace('login.html');
  });
}

// ─── API helper ───────────────────────────────────────────────────────────────

async function apiFetch(path, options = {}) {
  const res = await fetch(`${CONFIG.API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type':  'application/json',
      'Authorization': `Bearer ${SESSION.token}`,
      ...options.headers,
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Error ${res.status}`);
  }

  return res.status === 204 ? null : res.json();
}

// ─── Carga y renderizado ──────────────────────────────────────────────────────

async function cargarServicios() {
  const tbody = document.getElementById('tbody-servicios');
  tbody.innerHTML = `
    <tr>
      <td colspan="6" class="px-6 py-14 text-center text-sm text-gray-400">
        <div class="animate-spin w-4 h-4 border-2 border-gray-200 border-t-gray-400 rounded-full mx-auto mb-2"></div>
        Cargando catálogo...
      </td>
    </tr>`;

  try {
    servicios = await apiFetch('/servicios/?solo_activos=false&limit=200');
    renderizarTabla();
  } catch (e) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="px-6 py-10 text-center text-sm text-red-400">${escHtml(e.message)}</td>
      </tr>`;
  }
}

function renderizarTabla() {
  const tbody = document.getElementById('tbody-servicios');
  const countEl = document.getElementById('servicios-count');

  countEl.textContent = `${servicios.length} servicio${servicios.length !== 1 ? 's' : ''}`;

  if (!servicios.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="px-6 py-16 text-center text-sm text-gray-400">
          No hay servicios en el catálogo todavía.
        </td>
      </tr>`;
    return;
  }

  const fmt = new Intl.NumberFormat('es-AR', {
    style: 'currency', currency: 'ARS', minimumFractionDigits: 0,
  });

  tbody.innerHTML = servicios.map(s => {
    const tipoCss   = TIPO_BADGE[s.tipo_servicio]   ?? 'bg-gray-100 text-gray-600';
    const tipoLabel = TIPO_LABELS[s.tipo_servicio]  ?? s.tipo_servicio;
    const modalidad = MODALIDAD_LABELS[s.tipo_ejecucion] ?? s.tipo_ejecucion;
    const precio    = fmt.format(s.precio_base);

    const estadoBadge = s.activo
      ? `<span class="inline-flex items-center gap-1 text-xs text-green-700 bg-green-50 px-2 py-0.5 rounded-full font-medium">Activo</span>`
      : `<span class="inline-flex items-center gap-1 text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">Inactivo</span>`;

    const accionesAdmin = SESSION.esAdmin
      ? `<button data-id="${s.id}" data-accion="editar"
           class="px-2.5 py-1.5 text-xs text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
           Editar
         </button>
         ${s.activo
           ? `<button data-id="${s.id}" data-accion="inactivar"
                class="px-2.5 py-1.5 text-xs text-gray-400 border border-gray-200 rounded-lg hover:bg-red-50 hover:text-red-500 hover:border-red-200 transition-colors">
                Inactivar
              </button>`
           : ''}
         `
      : '';

    return `
      <tr class="hover:bg-gray-50/50 transition-colors ${s.activo ? '' : 'opacity-50'}">
        <td class="px-6 py-3.5">
          <p class="text-sm font-medium text-gray-900">${escHtml(s.nombre)}</p>
          ${s.descripcion
            ? `<p class="text-xs text-gray-400 font-light mt-0.5 truncate max-w-[260px]">${escHtml(s.descripcion)}</p>`
            : ''}
        </td>
        <td class="px-4 py-3.5">
          <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${tipoCss}">
            ${tipoLabel}
          </span>
        </td>
        <td class="px-4 py-3.5 text-sm text-gray-600">${modalidad}</td>
        <td class="px-4 py-3.5 text-sm text-gray-900 tabular-nums font-medium">${precio}</td>
        <td class="px-4 py-3.5">${estadoBadge}</td>
        <td class="px-4 py-3.5">
          <div class="flex items-center justify-end gap-1.5">${accionesAdmin}</div>
        </td>
      </tr>`;
  }).join('');

  tbody.querySelectorAll('[data-accion="editar"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const s = servicios.find(x => x.id === +btn.dataset.id);
      if (s) abrirPanelEditar(s);
    });
  });

  tbody.querySelectorAll('[data-accion="inactivar"]').forEach(btn => {
    btn.addEventListener('click', () => confirmarInactivar(+btn.dataset.id));
  });
}

// ─── Panel lateral ────────────────────────────────────────────────────────────

function inicializarPanel() {
  document.getElementById('panel-close-btn')?.addEventListener('click', cerrarPanel);
  document.getElementById('panel-cancel-btn')?.addEventListener('click', cerrarPanel);
  document.getElementById('panel-overlay')?.addEventListener('click', cerrarPanel);
  document.getElementById('btn-nuevo-servicio')?.addEventListener('click', abrirPanelCrear);

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') cerrarPanel();
  });
}

function abrirPanelCrear() {
  editandoId = null;
  document.getElementById('panel-title').textContent = 'Nuevo servicio';
  document.getElementById('panel-submit-btn').textContent = 'Crear servicio';
  resetForm();
  abrirPanel();
}

function abrirPanelEditar(s) {
  editandoId = s.id;
  document.getElementById('panel-title').textContent = 'Editar servicio';
  document.getElementById('panel-submit-btn').textContent = 'Guardar cambios';

  document.getElementById('form-nombre').value        = s.nombre;
  document.getElementById('form-descripcion').value   = s.descripcion ?? '';
  document.getElementById('form-precio_base').value   = s.precio_base;
  document.getElementById('form-tipo_ejecucion').value = s.tipo_ejecucion;
  document.getElementById('form-tipo_servicio').value  = s.tipo_servicio;
  document.getElementById('form-activo').checked      = s.activo;

  document.getElementById('panel-error').classList.add('hidden');
  abrirPanel();
}

function abrirPanel() {
  document.getElementById('panel-overlay').classList.remove('hidden');
  document.getElementById('slide-panel').classList.remove('translate-x-full');
}

function cerrarPanel() {
  document.getElementById('panel-overlay').classList.add('hidden');
  document.getElementById('slide-panel').classList.add('translate-x-full');
}

function resetForm() {
  document.getElementById('form-servicios').reset();
  document.getElementById('form-activo').checked = true;
  document.getElementById('panel-error').classList.add('hidden');
}

// ─── Formulario ───────────────────────────────────────────────────────────────

function inicializarFormulario() {
  document.getElementById('form-servicios')?.addEventListener('submit', async e => {
    e.preventDefault();
    await enviarFormulario();
  });
}

async function enviarFormulario() {
  const submitBtn = document.getElementById('panel-submit-btn');
  const errorEl  = document.getElementById('panel-error');

  const nombre    = document.getElementById('form-nombre').value.trim();
  const precio    = parseFloat(document.getElementById('form-precio_base').value);

  if (!nombre) {
    mostrarErrorPanel('El nombre técnico es obligatorio.');
    return;
  }
  if (!precio || precio <= 0) {
    mostrarErrorPanel('El precio base debe ser mayor a cero.');
    return;
  }

  errorEl.classList.add('hidden');

  const payload = {
    nombre,
    descripcion:    document.getElementById('form-descripcion').value.trim() || null,
    precio_base:    precio,
    tipo_ejecucion: document.getElementById('form-tipo_ejecucion').value,
    tipo_servicio:  document.getElementById('form-tipo_servicio').value,
    activo:         document.getElementById('form-activo').checked,
  };

  const textoOriginal = submitBtn.textContent;
  submitBtn.disabled = true;
  submitBtn.textContent = 'Guardando...';

  try {
    if (editandoId === null) {
      await apiFetch('/servicios/', { method: 'POST', body: JSON.stringify(payload) });
      mostrarToast('Servicio creado correctamente');
    } else {
      await apiFetch(`/servicios/${editandoId}`, { method: 'PUT', body: JSON.stringify(payload) });
      mostrarToast('Servicio actualizado correctamente');
    }
    cerrarPanel();
    await cargarServicios();
  } catch (e) {
    mostrarErrorPanel(e.message);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = textoOriginal;
  }
}

function mostrarErrorPanel(msg) {
  const el = document.getElementById('panel-error');
  el.textContent = msg;
  el.classList.remove('hidden');
}

// ─── Inactivar ────────────────────────────────────────────────────────────────

async function confirmarInactivar(id) {
  const s = servicios.find(x => x.id === id);
  if (!s) return;

  if (!confirm(`¿Desactivar el servicio "${s.nombre}"?\n\nEl servicio quedará inactivo pero se puede reactivar editándolo.`)) return;

  try {
    await apiFetch(`/servicios/${id}`, { method: 'DELETE' });
    mostrarToast('Servicio desactivado');
    await cargarServicios();
  } catch (e) {
    mostrarToast(e.message, true);
  }
}

// ─── Toast ────────────────────────────────────────────────────────────────────

let _toastTimer;

function mostrarToast(msg, esError = false) {
  const toast   = document.getElementById('toast');
  const toastMsg = document.getElementById('toast-msg');

  toastMsg.textContent = msg;
  toast.classList.toggle('bg-red-600',  esError);
  toast.classList.toggle('bg-gray-900', !esError);
  toast.classList.remove('hide');

  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => toast.classList.add('hide'), 3500);
}

// ─── Utilidades ───────────────────────────────────────────────────────────────

function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g,  '&amp;')
    .replace(/</g,  '&lt;')
    .replace(/>/g,  '&gt;')
    .replace(/"/g,  '&quot;');
}
