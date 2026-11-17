Vas a crear un bot de Telegram para **Telegram Serverless** (plataforma `tgcloud`) y entregármelo como un ZIP que publicaré con el bot Builder Hub. No me pidas ningún token ni contraseña.

PRIMERO lee las instrucciones completas (si puedes navegar; si no, sigue el resumen de abajo y avísame de que no pudiste abrirlo):
https://raw.githubusercontent.com/JoseKill09/builder-hub-bot/main/prompts/build-for-builder-hub.md
Ahí están los enlaces a la documentación oficial y el formato exacto del ZIP.

Respóndeme en español. Antes de programar, pregúntame en UN solo mensaje qué debe hacer el bot, en qué idioma serán sus mensajes, si quiero **mensajes enriquecidos** (mensajes con estructura: títulos, tablas, bloques desplegables y botones dentro del texto) o mensajes simples, si quiero Mini App (una web dentro de Telegram) o solo chat, y mi ID numérico de Telegram si hace falta un administrador. No me hagas preguntas técnicas: elige valores razonables y dime cuáles.

Resumen de las reglas obligatorias:
- Todo vive en `tgcloud/`: `schema.js`, `handlers/<tipo_de_update>.js` (plano; nombres como message, callback_query, inline_query), `endpoints/<nombre>.js`, `lib/**.js`.
- Solo JavaScript con módulos ES: sin TypeScript, sin `require`, sin npm, sin módulos de Node, sin `process.env`.
- Importa solo `sdk`, `sdk/db`, `sdk/api`, `sdk/fetch` y tus archivos con ruta relativa terminada en `.js`.
- Handlers y endpoints: `export default async function (payload, ctx)`. Toda llamada a la base de datos con `await`; sin foreign keys.
- No hay cron ni procesos en segundo plano. Las claves de terceros se guardan en la base de datos, que las pone el admin desde el bot.
- Mensajes enriquecidos (solo si dije que sí): lee primero https://raw.githubusercontent.com/JoseKill09/builder-hub-bot/main/docs/RICH-MESSAGES.md. Se envían con `api.sendRichMessage({ chat_id, rich_message: { html } })`, NO son HTML clásico, hay que escapar todo valor dinámico y tener un respaldo con mensajes clásicos.
- Mini App (opcional): HTML/JS simple en `webapp/` + `tgcloud.jsonc` con `{ "static": { "source": "webapp" } }`.

Entrégame un ZIP descargable con UNA sola carpeta raíz (sin node_modules ni .env), el árbol de archivos y una explicación breve. Si no puedes crear archivos, dame cada archivo en su bloque de código con la ruta completa. Relee tu código antes de entregarlo. Si te pego un informe de error de Builder Hub, corrige exactamente eso y dame el ZIP completo de nuevo.
