# Cambios

## 2.3 — 2026-11-19
- Primera versión entregada por el Actualizador (la 2.1 ya estaba instalada). Sin cambios de funcionamiento: sirve para comprobar el camino de entrega y que «Permitir proyecto» funciona.
- La versión que muestra el bot (pie del menú) pasa a 2.3.

## 2.1 — 2026-11-19
- **Tus proyectos, reconocidos:** cada bot que publicas queda apuntado (por su ID público de app y tu usuario). Al mandar un ZIP, el bot reconoce de qué proyecto es por su nombre; si tienes varios y no está claro, te pregunta cuál (o «Otro bot»). En cada proyecto, «📦 Actualizar».
- **🔑 Recordar acceso** (opcional, activado por defecto en la revisión): el token se guarda **cifrado** y las siguientes actualizaciones y vueltas atrás no lo piden. «Olvidar acceso» lo borra.
- **Acceso perdido:** si el token se regenera o revoca, el proyecto se sigue viendo (versiones, historial, descargas) pero para tocar el bot se pide el token nuevo.
- **🧾 Historial por proyecto** (publicaciones, actualizaciones, restauraciones y fallos).
- **🗑 Eliminar del bot:** borra versiones, copias del canal, historial y acceso guardado, con confirmación. El bot del usuario sigue funcionando.
- **Marca:** logotipo, foto de perfil, banners (es/en), nombre, descripciones y comandos; textos y comandos se ponen solos al arrancar y la foto desde 🛡 Panel → 🎨 Perfil del bot.
- Comandos nuevos: /projects, /prompt, /contact, /help.

## 2.0 — 2026-11-19
- **Actualizar con novedades:** manda el ZIP nuevo cuando quieras (sin pulsar nada): el bot enseña las novedades de su `CHANGELOG.md` desde la versión publicada (`v1.2 → v1.3`), pide el token y muestra la revisión con ✅ Actualizar / ✖️ Cancelar.
- **🗂 Mis proyectos:** historial de versiones de cada bot con fecha, novedades y SHA-256; ⬅️ volver a la anterior, ➡️ ir a la siguiente, restaurar cualquiera y 📥 descargar su ZIP.
- **Restaurar de forma segura:** solo se descarga esa versión (a memoria), se comprueba su SHA-256, se valida otra vez y se enseña el plan antes de tocar nada; al terminar se borra.
- **Anti-rollback:** `no_rollback_before` en `builderhub.json` impide volver más atrás y el bot dice hasta qué versión se puede; también bloquea si hiciera falta un cambio manual en la base de datos y avisa si alguna versión borró datos. Subir un ZIP más antiguo cuenta como volver atrás.
- **Si una actualización falla:** botón para volver a la versión que había, con el mismo token.
- **Copias en Telegram:** canal privado configurable desde el panel (💾); sin canal, la copia es el propio ZIP del usuario. Los ZIP del chat no se borran nunca.
- **Botón de menú de la Mini App activado solo** al publicar (sin pasar por @BotFather).
- **Cola con posición** cuando hay más publicaciones que huecos; huecos a la vez configurables en el panel (1–4).
- **Contacto con el propietario:** tipos, hilo, bandeja con filtros, respuestas rápidas, notas, destacados, resolver y avisar, retirar la última respuesta (48 h) y bloquear.
- Formato: `CHANGELOG.md` y `builderhub.json` documentados en `docs/FORMAT.md` y en los prompts; ejemplo actualizado.
- Corregido: la URL de la Mini App no salía si sus archivos no cambiaban.

## 1.1 — 17-11-2026
- Botón «Copiar prompt para la IA» en 📦 Formato: envía un prompt corto en un solo mensaje (es/en según el usuario) que manda a la IA a leer el completo en GitHub.
- Módulo de mensajes enriquecidos en los prompts (pregunta al usuario) y guía `docs/RICH-MESSAGES.md` con todas las etiquetas, límites, botones, errores típicos y patrón con respaldo.
- Manejador de errores y registro de cada mensaje recibido (sin contenido) para diagnosticar.

## 1.0 — 2026-11-17
- Primera versión de **Builder Hub** (*Ship your Telegram Serverless bot from any AI chat*).
- Publicación en 3 pasos desde el chat: token de acceso de Serverless (el mensaje se borra al momento) → ZIP del proyecto → revisión de cambios → publicar.
- Validación antes de publicar: estructura de `tgcloud/`, nombres de handlers (lista oficial de Telegram), endpoints, importaciones, `export default`, `require`, claves foráneas, sintaxis con `node --check` y Mini App. Informe de errores en inglés listo para pegárselo a la IA.
- Plan con módulos nuevos, cambiados y **borrados**, cambios de base de datos seguros, destructivos (con doble confirmación) y manuales.
- Publicación con el CLI oficial `@tgcloud/cli@0.2.0` (`push` + `migrate --safe`/`--yes`) e informe final (Mini App, webhook, recordatorio de regenerar el token).
- Seguridad: tokens solo en memoria y enmascarados en los registros; contenedor sin root, de solo lectura, sin capacidades y con los proyectos en memoria.
- Panel de administración: registro abierto/cerrado, tamaño máximo del ZIP, límite diario, bloqueos y estadísticas. Español e inglés.
- Documentación: `docs/FORMAT.md`, prompt para cualquier IA (`prompts/build-for-builder-hub.md`) y proyecto de ejemplo (`examples/hello-bot`).
