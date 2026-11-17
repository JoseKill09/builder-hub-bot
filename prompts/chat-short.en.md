You will build a Telegram bot for **Telegram Serverless** (platform `tgcloud`) and deliver it as a ZIP that I will publish with the Builder Hub bot. Do not ask me for any token or password.

FIRST, read the full instructions (if you can browse; if not, follow the summary below and tell me you couldn't open it):
https://raw.githubusercontent.com/JoseKill09/builder-hub-bot/main/prompts/build-for-builder-hub.md
It links to the official docs and to the exact ZIP format.

Reply to me in my language. Before coding, ask me in ONE message what the bot must do, which language its messages use, whether I want **Rich Messages** (structured messages with headings, tables, collapsible blocks and buttons inside the text) or simple messages, whether I want a Mini App (web page inside Telegram) or chat only, and my numeric Telegram ID if an admin is needed. Don't ask technical questions: pick sensible defaults and tell me.

Summary of the hard rules:
- Everything lives in `tgcloud/`: `schema.js`, `handlers/<update_type>.js` (flat; names like message, callback_query, inline_query), `endpoints/<name>.js`, `lib/**.js`.
- JavaScript ES modules only: no TypeScript, no `require`, no npm, no Node built-ins, no `process.env`.
- Import only `sdk`, `sdk/db`, `sdk/api`, `sdk/fetch` and your own files by relative path ending in `.js`.
- Handlers/endpoints: `export default async function (payload, ctx)`. Every DB call is awaited; no foreign keys.
- No cron or background jobs. Store third-party secrets in the database, set by the admin from the bot.
- Rich Messages (only if I said yes): first read https://raw.githubusercontent.com/JoseKill09/builder-hub-bot/main/docs/RICH-MESSAGES.md. They use `api.sendRichMessage({ chat_id, rich_message: { html } })`, are NOT classic HTML, need every dynamic value escaped and a classic fallback.
- Mini App (optional): plain HTML/JS in `webapp/` + `tgcloud.jsonc` with `{ "static": { "source": "webapp" } }`.

Deliver a downloadable ZIP with ONE root folder (no node_modules, no .env), the file tree, and a short explanation. If you can't create files, give each file in its own code block with its full path. Re-read your code before delivering. If I paste an error report from Builder Hub, fix exactly that and give me the complete new ZIP.
