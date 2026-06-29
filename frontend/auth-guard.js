/**
 * auth-guard.js — Middleware de seguridad para todas las pantallas internas.
 *
 * ORDEN DE CARGA OBLIGATORIO en el HTML:
 *   <script src="config.js"></script>
 *   <script src="auth-guard.js"></script>   ← segundo, antes que cualquier script de negocio
 *   <script src="dashboard.js"></script>    ← o cliente.js, usuarios.js, etc.
 *
 * Comportamiento:
 *   1. Sin sesión → redirige a login.html de inmediato (sin flash de pantalla).
 *   2. Con sesión → expone window.SESSION con token y datos del usuario.
 *   3. Página admin-only + rol soporte → redirige a index.html con alerta.
 *   4. Controla la visibilidad de elementos marcados con data-requiere-admin.
 */

;(function () {
  'use strict';

  // ── 1. Verificar sesión ────────────────────────────────────────────────────

  const token   = localStorage.getItem('dmg_token');
  const userRaw = localStorage.getItem('dmg_user');

  if (!token || !userRaw) {
    window.location.replace('login.html');
    return; // detener toda ejecución posterior
  }

  let user;
  try {
    user = JSON.parse(userRaw);
  } catch {
    localStorage.clear();
    window.location.replace('login.html');
    return;
  }

  // ── 2. Exponer sesión globalmente ──────────────────────────────────────────

  window.SESSION = Object.freeze({
    token,
    user,
    rol:      user.rol      ?? 'soporte',
    username: user.username ?? '',
    esAdmin:  user.rol === 'admin',
  });

  // ── 3. Verificar acceso a páginas admin-only ───────────────────────────────

  const PAGINAS_SOLO_ADMIN = ['usuarios.html'];
  const paginaActual = location.pathname.split('/').pop().toLowerCase() || 'index.html';

  if (PAGINAS_SOLO_ADMIN.includes(paginaActual) && !SESSION.esAdmin) {
    // Ocultar el documento para evitar flash de contenido prohibido
    document.documentElement.style.visibility = 'hidden';

    document.addEventListener('DOMContentLoaded', () => {
      document.documentElement.style.visibility = '';
      _mostrarAccesoDenegado();
    });
  }

  // ── 4. Aplicar restricciones visuales post-carga ────────────────────────────
  // Oculta elementos marcados con data-requiere-admin si el usuario es soporte.

  document.addEventListener('DOMContentLoaded', () => {
    if (!SESSION.esAdmin) {
      document.querySelectorAll('[data-requiere-admin]').forEach((el) => {
        el.classList.add('hidden');
      });
    }
  });

  // ── Mobile sidebar toggle ─────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    const toggle  = document.getElementById('sidebar-toggle');
    if (!sidebar || !toggle) return;

    const open  = () => { sidebar.classList.remove('-translate-x-full'); overlay?.classList.remove('hidden'); document.body.classList.add('overflow-hidden'); };
    const close = () => { sidebar.classList.add('-translate-x-full');    overlay?.classList.add('hidden');    document.body.classList.remove('overflow-hidden'); };

    toggle.addEventListener('click', open);
    overlay?.addEventListener('click', close);
    sidebar.querySelectorAll('a[href]').forEach(a =>
      a.addEventListener('click', () => { if (window.innerWidth < 1024) close(); })
    );
  });

  // ── Helpers internos ────────────────────────────────────────────────────────

  function _mostrarAccesoDenegado() {
    document.body.innerHTML = `
      <div class="min-h-screen bg-gray-50 flex items-center justify-center p-6" style="font-family:'Inter',sans-serif">
        <div class="bg-white border border-gray-200 rounded-2xl p-10 max-w-sm w-full text-center shadow-sm">
          <div class="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-red-50 mb-5">
            <svg class="w-5 h-5 text-red-400" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round"
                d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z"/>
            </svg>
          </div>
          <h2 class="text-sm font-semibold text-gray-900 mb-1">Acceso denegado</h2>
          <p class="text-xs text-gray-400 font-light mb-6">
            Se requieren permisos de Administrador para acceder a esta pantalla.
          </p>
          <a href="index.html"
            class="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-lg hover:bg-gray-800 transition">
            Volver al dashboard
          </a>
        </div>
      </div>`;
  }

})();
