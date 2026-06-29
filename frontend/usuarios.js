/**
 * usuarios.js — Gestión de usuarios internos · DM Global
 *
 * Requiere auth-guard.js cargado antes (valida que el rol sea 'admin').
 *
 * Endpoints consumidos:
 *   GET  /auth/usuarios          → lista el staff
 *   POST /auth/usuarios          → crea un operador
 *   PUT  /auth/usuarios/{id}     → actualiza rol o activo
 */

'use strict';

// ── Estado en memoria ─────────────────────────────────────────────────────────

let usuarios = [];
let editandoId = null; // null = crear, number = editar

// ── Auth fetch ────────────────────────────────────────────────────────────────

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

// ── Formateo ──────────────────────────────────────────────────────────────────

const ROL_CLS = {
  admin:   'text-violet-700 bg-violet-50 ring-1 ring-inset ring-violet-600/20',
  soporte: 'text-blue-600  bg-blue-50  ring-1 ring-inset ring-blue-600/20',
};

const ESTADO_CLS = {
  true:  'text-green-700 bg-green-50 ring-1 ring-inset ring-green-600/20',
  false: 'text-gray-500  bg-gray-100 ring-1 ring-inset ring-gray-500/20',
};

function badgeRol(rol) {
  const cls = ROL_CLS[rol] ?? 'text-gray-500 bg-gray-100';
  return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${cls}">${rol}</span>`;
}

function badgeEstado(activo) {
  const cls   = ESTADO_CLS[String(activo)];
  const label = activo ? 'activo' : 'inactivo';
  return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${cls}">${label}</span>`;
}

// ── Render tabla ──────────────────────────────────────────────────────────────

function renderUsuarios(lista) {
  const tbody = document.getElementById('tbody-usuarios');
  tbody.innerHTML = '';

  if (lista.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="px-6 py-10 text-center text-sm text-gray-400">Sin usuarios registrados.</td></tr>`;
    return;
  }

  const sesionUsername = SESSION?.username ?? '';

  lista.forEach((u) => {
    const esMismo   = u.username === sesionUsername;
    const btnEditar = `
      <button
        class="px-2.5 py-1 text-xs border border-gray-200 rounded-lg text-gray-600 hover:bg-gray-50 transition whitespace-nowrap"
        data-action="editar" data-usuario-id="${u.id}">
        Editar rol
      </button>`;

    const btnToggle = esMismo ? '' : `
      <button
        class="px-2.5 py-1 text-xs border border-gray-200 rounded-lg ${u.activo ? 'text-red-600 hover:bg-red-50' : 'text-green-700 hover:bg-green-50'} transition whitespace-nowrap"
        data-action="toggle-activo" data-usuario-id="${u.id}" data-activo="${u.activo}">
        ${u.activo ? 'Inactivar' : 'Reactivar'}
      </button>`;

    const tr = document.createElement('tr');
    tr.id = `row-usuario-${u.id}`;
    tr.className = 'hover:bg-gray-50/60 transition-colors';
    tr.innerHTML = `
      <td class="px-6 py-3.5">
        <div class="flex items-center gap-2.5">
          <span class="inline-flex items-center justify-center w-7 h-7 rounded-full bg-gray-100 text-gray-600 text-xs font-medium shrink-0">
            ${u.username.charAt(0).toUpperCase()}
          </span>
          <span class="text-sm font-medium text-gray-900">${u.username}</span>
          ${esMismo ? '<span class="text-[10px] text-gray-400">(tú)</span>' : ''}
        </div>
      </td>
      <td class="px-4 py-3.5 text-sm text-gray-500">${u.email}</td>
      <td class="px-4 py-3.5">${badgeRol(u.rol)}</td>
      <td class="px-4 py-3.5">${badgeEstado(u.activo)}</td>
      <td class="px-4 py-3.5">
        <div class="flex items-center justify-end gap-1.5">
          ${btnEditar}${btnToggle}
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

// ── Carga desde API ───────────────────────────────────────────────────────────

async function cargarUsuarios() {
  try {
    usuarios = await apiFetch('/auth/usuarios');
    renderUsuarios(usuarios);
  } catch (err) {
    document.getElementById('tbody-usuarios').innerHTML = `
      <tr><td colspan="5" class="px-6 py-8 text-center text-sm text-red-400">
        Error al cargar usuarios: ${err.message}
      </td></tr>`;
  }
}

// ── Modal ─────────────────────────────────────────────────────────────────────

function abrirModalCrear() {
  editandoId = null;
  document.getElementById('modal-usuario-title').textContent = 'Registrar nuevo operador';
  document.getElementById('modal-usuario-confirm').textContent = 'Registrar operador';
  document.getElementById('campo-username-wrap').classList.remove('hidden');
  document.getElementById('campo-email-wrap').classList.remove('hidden');
  document.getElementById('campo-password-wrap').classList.remove('hidden');
  document.getElementById('modal-username').value = '';
  document.getElementById('modal-email').value    = '';
  document.getElementById('modal-password').value = '';
  document.getElementById('modal-rol').value      = 'soporte';
  setModalError('');
  document.getElementById('modal-usuario').classList.remove('hidden');
  document.getElementById('modal-username').focus();
}

function abrirModalEditar(usuario) {
  editandoId = usuario.id;
  document.getElementById('modal-usuario-title').textContent   = `Editar rol — ${usuario.username}`;
  document.getElementById('modal-usuario-confirm').textContent = 'Guardar cambios';
  document.getElementById('campo-username-wrap').classList.add('hidden');
  document.getElementById('campo-email-wrap').classList.add('hidden');
  document.getElementById('campo-password-wrap').classList.add('hidden');
  document.getElementById('modal-rol').value = usuario.rol;
  setModalError('');
  document.getElementById('modal-usuario').classList.remove('hidden');
  document.getElementById('modal-rol').focus();
}

function cerrarModal() {
  document.getElementById('modal-usuario').classList.add('hidden');
  editandoId = null;
}

function setModalError(msg) {
  const el = document.getElementById('modal-usuario-error');
  el.textContent = msg;
  el.classList.toggle('hidden', !msg);
}

// ── Submit del formulario ─────────────────────────────────────────────────────

document.getElementById('form-usuario').addEventListener('submit', async (e) => {
  e.preventDefault();
  setModalError('');

  const btn = document.getElementById('modal-usuario-confirm');
  btn.disabled = true;
  btn.textContent = 'Guardando...';

  try {
    if (editandoId !== null) {
      // ── Editar rol ──────────────────────────────────────────────────────────
      const updated = await apiFetch(`/auth/usuarios/${editandoId}`, {
        method: 'PUT',
        body: JSON.stringify({ rol: document.getElementById('modal-rol').value }),
      });
      const idx = usuarios.findIndex(u => u.id === editandoId);
      if (idx !== -1) usuarios[idx] = updated;
    } else {
      // ── Crear usuario ───────────────────────────────────────────────────────
      const username = document.getElementById('modal-username').value.trim();
      const email    = document.getElementById('modal-email').value.trim();
      const password = document.getElementById('modal-password').value;
      const rol      = document.getElementById('modal-rol').value;

      if (!username || !email || !password) {
        setModalError('Completá todos los campos.');
        return;
      }

      const nuevo = await apiFetch('/auth/usuarios', {
        method: 'POST',
        body: JSON.stringify({ username, email, password, rol }),
      });
      usuarios.push(nuevo);
    }

    renderUsuarios(usuarios);
    cerrarModal();
  } catch (err) {
    setModalError(err.message);
  } finally {
    btn.disabled    = false;
    btn.textContent = editandoId ? 'Guardar cambios' : 'Registrar operador';
  }
});

// ── Delegación de eventos — tabla ─────────────────────────────────────────────

document.getElementById('tbody-usuarios').addEventListener('click', async (e) => {
  const btn = e.target.closest('button[data-action][data-usuario-id]');
  if (!btn || btn.disabled) return;

  const userId = parseInt(btn.dataset.usuarioId, 10);
  const accion = btn.dataset.action;
  const usuario = usuarios.find(u => u.id === userId);
  if (!usuario) return;

  if (accion === 'editar') {
    abrirModalEditar(usuario);
    return;
  }

  if (accion === 'toggle-activo') {
    const nuevoEstado = btn.dataset.activo === 'true' ? false : true;
    const accionLabel = nuevoEstado ? 'reactivar' : 'inactivar';

    const ok = window.confirm(
      `¿Confirmar ${accionLabel} la cuenta de "${usuario.username}"?\n` +
      (nuevoEstado ? '' : 'El usuario perderá acceso inmediatamente a la intranet.')
    );
    if (!ok) return;

    btn.disabled = true;
    try {
      const updated = await apiFetch(`/auth/usuarios/${userId}`, {
        method: 'PUT',
        body: JSON.stringify({ activo: nuevoEstado }),
      });
      const idx = usuarios.findIndex(u => u.id === userId);
      if (idx !== -1) usuarios[idx] = updated;
      renderUsuarios(usuarios);
    } catch (err) {
      alert(`Error: ${err.message}`);
      btn.disabled = false;
    }
  }
});

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {

  // Poblar datos del usuario en el sidebar
  if (window.SESSION) {
    document.getElementById('sidebar-username').textContent = SESSION.username;
    document.getElementById('sidebar-rol').textContent = SESSION.esAdmin ? 'Administrador' : 'Soporte';
    document.getElementById('sidebar-avatar').textContent = SESSION.username.charAt(0).toUpperCase();
  }

  cargarUsuarios();

  document.getElementById('btn-nuevo-usuario').addEventListener('click', abrirModalCrear);
  document.getElementById('modal-usuario-close').addEventListener('click', cerrarModal);
  document.getElementById('modal-usuario-cancel').addEventListener('click', cerrarModal);
  document.getElementById('modal-usuario').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) cerrarModal();
  });

  document.getElementById('logout-btn').addEventListener('click', () => {
    localStorage.clear();
    window.location.replace('login.html');
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') cerrarModal();
  });
});
