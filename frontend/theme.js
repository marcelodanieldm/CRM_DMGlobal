/**
 * theme.js — Tokens de tema "Terminal de Operaciones" · DM Global
 *
 * Debe cargarse INMEDIATAMENTE DESPUÉS de:
 *   <script src="https://cdn.tailwindcss.com"></script>
 * y ANTES de cualquier marcado que use clases de Tailwind.
 *
 * Extiende la config de Tailwind (Play CDN) para usar una tipografía
 * monoespaciada propia en números, IDs y datos tabulares (CUIT, precios,
 * métricas), reforzando la identidad "panel de control" del CRM.
 * No reemplaza la paleta: los colores (slate/cyan/emerald/amber/rose)
 * ya son los de Tailwind por defecto, aplicados directamente en el HTML.
 */
tailwind.config = {
  theme: {
    extend: {
      fontFamily: {
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
    },
  },
};
