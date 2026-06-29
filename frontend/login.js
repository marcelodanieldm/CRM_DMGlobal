/**
 * login.js — Autenticación de usuarios internos · DM Global
 *
 * Flujo:
 *  1. Si ya hay una sesión activa → redirigir a index.html directamente.
 *  2. Al enviar el formulario → POST a /auth/login (OAuth2 form).
 *  3. Decodificar el JWT recibido → extraer username y rol del payload.
 *  4. Persistir token + datos de usuario en localStorage.
 *  5. Redirigir a index.html.
 */

'use strict';

// ── Si ya hay sesión, no mostrar el login ─────────────────────────────────────

if (localStorage.getItem('dmg_token')) {
  window.location.replace('index.html');
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Decodifica el payload de un JWT sin verificar la firma.
 * La verificación de firma ocurre en el servidor en cada request protegido.
 */
function decodeJwtPayload(token) {
  try {
    const [, payloadB64] = token.split('.');
    const json = atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(json);
  } catch {
    return {};
  }
}

function setError(msg) {
  const el = document.getElementById('login-error');
  el.textContent = msg;
  el.classList.toggle('hidden', !msg);
}

function setLoading(isLoading) {
  const btn = document.getElementById('login-btn');
  btn.disabled    = isLoading;
  btn.textContent = isLoading ? 'Verificando...' : 'Ingresar';
}

// ── Login ─────────────────────────────────────────────────────────────────────

async function doLogin(username, password) {
  const body = new URLSearchParams({ username, password });

  const res = await fetch(`${CONFIG.API_BASE_URL}/auth/login`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });

  if (res.status === 401) throw new Error('Usuario o contraseña incorrectos');
  if (!res.ok)           throw new Error(`Error del servidor (${res.status})`);

  const { access_token: token } = await res.json();

  // Extraer claims del JWT para persistir el usuario
  const payload = decodeJwtPayload(token);
  const user = {
    username: payload.sub ?? username,
    rol:      payload.rol ?? 'soporte',
  };

  // Persistir en localStorage (sessionStorage si se prefiere vida de pestaña)
  localStorage.setItem('dmg_token', token);
  localStorage.setItem('dmg_user',  JSON.stringify(user));

  return user;
}

// ── Form handler ──────────────────────────────────────────────────────────────

document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  setError('');

  const username = document.getElementById('input-email').value.trim();
  const password = document.getElementById('input-password').value;

  if (!username || !password) {
    setError('Completá todos los campos.');
    return;
  }

  setLoading(true);

  try {
    const user = await doLogin(username, password);
    // Redirigir según el rol (admin → dashboard, soporte → dashboard)
    window.location.replace('index.html');
  } catch (err) {
    setError(err.message);
    document.getElementById('input-password').value = '';
    document.getElementById('input-password').focus();
  } finally {
    setLoading(false);
  }
});
