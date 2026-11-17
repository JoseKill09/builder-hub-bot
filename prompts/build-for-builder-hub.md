# Prompt: build a Telegram Serverless bot for Builder Hub

Copy everything below the line into any AI chat (Claude, ChatGPT, Gemini…), then describe the bot you want.

---

You are going to build a **Telegram bot that runs on Telegram Serverless** (the `tgcloud` platform) and deliver it as a **ZIP file in the Builder Hub format**. I will publish that ZIP myself with the Builder Hub bot (@BuilderHubBot), so you do **not** need, and must **not** ask for, any token or password.

## 1. Read these sources first (if you can browse)

1. https://core.telegram.org/bots/serverless.md — the official platform docs (raw Markdown).
2. https://raw.githubusercontent.com/JoseKill09/builder-hub-bot/main/docs/FORMAT.md — the exact ZIP format.
3. https://github.com/JoseKill09/telegram-serverless-handbook — what the official docs don't say (gotchas, patterns).
4. For any Telegram method you use: `https://core.telegram.org/bots/api/methods/<methodname>.md` (lowercase), and for Mini Apps `https://core.telegram.org/bots/webapps.md`.

If you cannot browse, follow the rules in section 3 strictly: they summarize those sources.

## 2. Ask me only what you need

Before writing code, ask me (in one message, with sensible defaults I can accept):
- What the bot must do (main features, commands, buttons).
- The language(s) of the bot's messages.
- Whether I want a **Mini App** (a web page inside Telegram) or chat only.
- Anything that needs a decision only I can make (for example, who the admin is: ask for my numeric Telegram ID, never for tokens).

Do not ask technical questions I would not understand: choose sensible defaults and tell me what you chose.

## 3. Hard rules (the platform rejects anything else)

- Everything that runs lives in a `tgcloud/` folder:
  - `tgcloud/schema.js` (database tables, optional),
  - `tgcloud/handlers/<update_type>.js` — flat; file names must be Telegram update types (`message`, `callback_query`, `inline_query`, `my_chat_member`, `channel_post`, `pre_checkout_query`…),
  - `tgcloud/endpoints/<name>.js` — functions the Mini App calls, flat, identifier names,
  - `tgcloud/lib/**.js` — shared code.
- **JavaScript ES modules only.** No TypeScript, no `require`, no npm packages, no Node built-ins (`fs`, `path`, `crypto`, `process`, `Buffer`). The runtime is a V8 isolate.
- Import **only** `sdk`, `sdk/db`, `sdk/api`, `sdk/fetch`, and your own files by **relative path ending in `.js`** (`import { x } from '../lib/x.js'`).
- Handlers: `export default async function (payload, ctx)`. The payload is the update's object (for `handlers/message.js` it is the Message). Endpoints: `export default async function (input, ctx)`, user in `ctx.initData.user` (already verified); refuse with `throw new EndpointError(text, { code })` from `sdk`.
- Bot API: `import { api } from 'sdk'` and `await api.sendMessage({ chat_id, text })` — snake_case parameters, the result comes unwrapped, failures throw `BotApiError` (`.code`, `.description`).
- Database: `import { db } from 'sdk'`, schema DSL from `sdk/db` (`table`, `integer`, `text`, `boolean`, `json`, `index`, `sql`, `eq`, `and`…), Drizzle-like. **Every query is awaited.** **No foreign keys** (never `.references()`). `.returning().run()` returns an array. Sort by an expression with ``sql`… DESC` `` (not `desc(sql…)`).
- HTTP to other services: `import { fetch } from 'sdk'`.
- There are **no scheduled jobs / cron** and no long-running processes: do work when an update or endpoint call arrives.
- Keep secrets for third-party services out of the code: let the admin set them from the bot and store them in the database.
- **Mini App:** plain HTML/CSS/JS that needs no build (or give me the already built output). Put it in `webapp/`, include `https://telegram.org/js/telegram-web-app.js`, call endpoints with `Telegram.WebApp.Serverless.call('name', input, (err, result) => …)`, and add a `tgcloud.jsonc` at the root: `{ "static": { "source": "webapp" } }`. Never put files under `webapp/api/`.
- No `node_modules/`, no `.tgcloud/`, no `package.json` needed.

## 4. Deliver

1. Show me the **file tree** and a short explanation of what each part does.
2. Give me the project as a **downloadable ZIP** (if you can create files). If you cannot, give every file in its own code block with its full path as the title, and tell me how to make the ZIP on my phone (Android: Files app → select the folder → Compress; iPhone: Files → long press the folder → Compress).
3. Tell me the next steps:
   - open @BuilderHubBot → 🚀 Publish → send the **Serverless access token** (@BotFather → my bot → Serverless → CLI Access) → send the ZIP → review → Publish;
   - then regenerate the access token in @BotFather;
   - if there is a Mini App: set its URL in @BotFather (Builder Hub shows it after publishing) or add a menu button from the code with `setChatMenuButton`.

## 5. Check your work before delivering

- [ ] Every file in `tgcloud/handlers/` is named after a real update type.
- [ ] Every relative import ends in `.js` and points to a file that exists in the ZIP.
- [ ] No `require`, no npm imports, no `process.env`, no Node built-ins.
- [ ] Every handler and endpoint has `export default`.
- [ ] Every database call is awaited; no foreign keys.
- [ ] The code is syntactically valid JavaScript (re-read it).
- [ ] If there is a Mini App: `tgcloud.jsonc` exists and `webapp/index.html` loads `telegram-web-app.js`.

## 6. When Builder Hub reports errors

Builder Hub replies with a report like `Builder Hub could not deploy the project. Fix these problems…`. When I paste it to you, fix **exactly** those problems, keep everything else the same, and give me the complete new ZIP again.
