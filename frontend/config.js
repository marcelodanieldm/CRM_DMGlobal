/**
 * config.js — Configuración centralizada del frontend · DM Global
 *
 * ORDEN DE CARGA OBLIGATORIO en el HTML:
 *   <script src="config.js"></script>      ← primero
 *   <script src="dashboard.js"></script>   ← o cualquier script operativo
 *
 * Todos los scripts leen de CONFIG; nunca hardcodear URLs o tokens.
 *
 * En producción cambiar ENTORNO a 'produccion' y actualizar API_BASE_URL.
 * No incluir secretos reales en este archivo si va al repositorio público.
 */

const CONFIG = Object.freeze({

  // URL base del backend FastAPI (sin barra final).
  // Todos los paths de fetch son relativos a este origen.
  // Ejemplo producción: 'https://api.dmglobal.com/api/v1'
  API_BASE_URL: 'http://localhost:8001/api/v1',

  // Token para el endpoint de validación de acceso de bots internos.
  // Solo necesario si algún componente del panel llama a /validar-acceso.
  // En producción leer desde una variable de entorno o un meta tag seguro.
  BOT_API_KEY: '',

  // 'desarrollo' activa los fallbacks a datos mock cuando la API no responde.
  // 'produccion' trata cualquier error de red como error real (sin mock).
  ENTORNO: 'desarrollo',  // 'desarrollo' | 'produccion'

});
