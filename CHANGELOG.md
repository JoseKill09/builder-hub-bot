# Cambios

## 1.0 — 2026-11-17
- Primera versión de **Builder Hub** (*Ship your Telegram Serverless bot from any AI chat*).
- Publicación en 3 pasos desde el chat: token de acceso de Serverless (el mensaje se borra al momento) → ZIP del proyecto → revisión de cambios → publicar.
- Validación antes de publicar: estructura de `tgcloud/`, nombres de handlers (lista oficial de Telegram), endpoints, importaciones, `export default`, `require`, claves foráneas, sintaxis con `node --check` y Mini App. Informe de errores en inglés listo para pegárselo a la IA.
- Plan con módulos nuevos, cambiados y **borrados**, cambios de base de datos seguros, destructivos (con doble confirmación) y manuales.
- Publicación con el CLI oficial `@tgcloud/cli@0.2.0` (`push` + `migrate --safe`/`--yes`) e informe final (Mini App, webhook, recordatorio de regenerar el token).
- Seguridad: tokens solo en memoria y enmascarados en los registros; contenedor sin root, de solo lectura, sin capacidades y con los proyectos en memoria.
- Panel de administración: registro abierto/cerrado, tamaño máximo del ZIP, límite diario, bloqueos y estadísticas. Español e inglés.
- Documentación: `docs/FORMAT.md`, prompt para cualquier IA (`prompts/build-for-builder-hub.md`) y proyecto de ejemplo (`examples/hello-bot`).
