# Builder Hub

**Ship your Telegram Serverless bot from any AI chat.**

Builder Hub is a Telegram bot that publishes [Telegram Serverless](https://core.telegram.org/bots/serverless) projects for you. You (or any AI chat: Claude, ChatGPT, Gemini…) prepare the project as a ZIP; Builder Hub checks it, shows you exactly what will change and uploads it to *your* bot with the official `tgcloud` CLI.

It exists for people who don't have a computer, a terminal or an AI agent that can run commands. The only things you need are Telegram and an AI chat.

> Want an AI that does everything end to end (code, deploy, test) on its own? See the companion repository
> [telegram-serverless-handbook](https://github.com/JoseKill09/telegram-serverless-handbook).

## How it works

1. Create your bot in [@BotFather](https://t.me/BotFather) and turn on **Serverless** (your bot → Serverless).
2. Ask your AI to build the project using [`prompts/build-for-builder-hub.md`](prompts/build-for-builder-hub.md). It must follow [`docs/FORMAT.md`](docs/FORMAT.md) and give you a ZIP.
3. Open Builder Hub, tap **🚀 Publish**, send your **Serverless access token** (BotFather → your bot → Serverless → CLI Access) and the ZIP.
4. Builder Hub checks the project. If something is wrong, it gives you a ready-to-paste error report for your AI.
5. You review the plan (new / changed / **deleted** modules, database changes) and tap **✅ Publish**.
6. **Regenerate your access token** in BotFather afterwards, so the one you shared stops working.

To **update** a bot later, just send its new ZIP to Builder Hub at any time: it shows you what's new (from the ZIP's `CHANGELOG.md`, every version newer than the one your bot has), then asks for the token and the confirmation.

## Features

- **Knows your projects.** Every bot you publish is remembered (by its public app ID, per user). When you send a ZIP, Builder Hub recognises which project it belongs to (by its name), or asks you if you have several; with saved access it goes straight to the review.
- **Updates with "what's new".** Send a ZIP whenever you want; Builder Hub compares it with the published version (`v1.2 → v1.3`), shows the new changelog entries and the plan, and you confirm or cancel.
- **Version history per bot** (🗂 My projects): every published version with its date, changelog and SHA-256. Go **⬅️ back** to the previous one, **➡️ forward** again, restore any version, or **📥 download** its ZIP.
- **Safe restores.** Only the chosen version is downloaded (to RAM), its SHA-256 must match, it is validated again and you see the plan before anything changes.
- **Anti-rollback.** A version can declare `no_rollback_before` in `builderhub.json`; Builder Hub then refuses to go back further and says so. It also blocks a rollback that would need a manual database change, and warns when a version in between deleted data. Uploading an older ZIP counts as a rollback too.
- **Recovery after a failed update:** if publishing fails, one tap goes back to the version you had, with the same token (no need to send it again).
- **Copies in Telegram, not on the server.** With a private channel set in the panel, every published ZIP is stored there (by `file_id`, no re-upload). Without it, the version points to the user's own ZIP in the chat. **Builder Hub never deletes ZIP messages** — only the message that carries a token.
- **Mini App menu button turned on automatically** after publishing (no BotFather step), unless the bot already has one.
- **Queue:** a few publications run at the same time (panel setting, 1–4); everyone else waits in order and sees their position.
- **Contact:** users write to the owner (idea, bug, question…) and get the answer in the chat. The owner has an inbox with filters, quick replies, notes, stars, "solve and notify", retracting the last reply (48 h) and blocking.
- **Copyable AI prompt** in one message, in the user's language (📦 Format → 📋).
- **Per-project history** of every publication, update, restore and failure.
- **Bot profile out of the box:** name, descriptions and commands (es/en) are set at start-up; the profile photo from the panel. Brand assets in [`brand/`](brand/).

## Security model

- **Your code never runs on the Builder Hub server.** It is only validated and uploaded; it runs on Telegram's infrastructure, inside your bot.
- **Tokens are never logged, and only stored if you ask.** The message where you send the token is deleted immediately; the token is passed to the CLI only through an environment variable and masked in every log line. By default it lives in memory for one publication. If you turn on **🔑 Remember access**, it is stored **encrypted** (Fernet; key in `SECRET_KEY` or a `data/vault.key` file with mode 600) so that next time you only send the ZIP. Forget it from the bot at any time, or regenerate it in BotFather: the project then shows "access lost" — you still see it, but nothing is changed on Telegram until you send a new token.
- **Delete a project** and Builder Hub erases everything about it: versions, channel copies, history and saved access (your bot keeps running on Telegram; your ZIPs in the chat are yours to delete).
- **No surprises with your data.** Before publishing you see every change. Safe database changes (new tables/columns) are applied with `migrate --safe`; changes that delete data are listed separately and are only applied after an explicit second confirmation.
- **Hardened container:** non-root user, read-only filesystem, projects unpacked in RAM (`tmpfs`) and deleted after each job, no Linux capabilities, memory and process limits.
- **ZIP hygiene:** absolute paths, `..`, symlinks, encrypted entries, oversized files and ZIP bombs are rejected; `node_modules/`, `.tgcloud/`, `.git/` and `.env*` are ignored.
- You can read every line of code here, or run your own instance.

## What Builder Hub checks

| Check | Why |
|---|---|
| `tgcloud/` layout: `schema.js`, flat `handlers/` and `endpoints/`, nested `lib/` | The platform rejects anything else |
| Handler names are real update types (list taken live from Telegram) | `handlers/mesage.js` would silently never run |
| Endpoint names are identifiers | Required by the platform |
| Imports: only `sdk`, `sdk/db`, `sdk/api`, `sdk/fetch` and relative paths ending in `.js` that exist | No npm packages at runtime |
| `export default` in handlers and endpoints | It is what the platform calls |
| No `require()`, warnings for `process.env` and dynamic `import()` | Not available / not documented at runtime |
| No foreign keys in `schema.js` | `.references()` throws at deploy time |
| JavaScript syntax (`node --check` as ES modules) | Catches typos before they reach your bot |
| Mini App: `static.source` exists, has `index.html`, nothing under `/api/`, looks built | The platform does not run your build |

## Run your own instance

```bash
git clone https://github.com/JoseKill09/builder-hub-bot && cd builder-hub-bot
cp .env.example .env           # then fill BOT_TOKEN and ADMIN_IDS
docker compose up -d --build
```

| Variable | Meaning |
|---|---|
| `BOT_TOKEN` | Bot API token of *your* Builder Hub bot (from BotFather) |
| `ADMIN_IDS` | Telegram user IDs allowed to open the admin panel (comma-separated) |
| `PUID` / `PGID` | Owner of `./data` on the host (default `1000:10`) |
| `RICH_MESSAGES` | `0` to force classic HTML messages |
| `MAX_PARALLEL` | Default for "publications at once" (the panel setting wins; default 2) |
| `JOB_TTL` | Seconds before an unfinished publication is cancelled and forgotten (default 900) |
| `SECRET_KEY` | Optional key to encrypt remembered tokens (default: generated in `data/vault.key`) |

Runtime settings (sign-ups and contact open/closed, max ZIP size, daily limit per user, publications at once, copies channel, blocked users, support inbox) are changed from the **🛡 Panel** inside the bot.

## Development

```bash
docker build -t builder-hub .
docker run --rm builder-hub python -m pytest -q tests                  # unit tests
# Try the deploy core without Telegram (plan only, add --publish to publish):
docker run --rm -e TGCLOUD_TOKEN=app…:… -v "$PWD/my.zip:/in/p.zip:ro" -v "$PWD/tools:/app/tools:ro" \
  builder-hub python tools/try_deploy.py /in/p.zip
```

| Path | What it is |
|---|---|
| `bot/deploy/zipsafe.py` | Safe ZIP extraction |
| `bot/deploy/validate.py` | Project validation (rules above) and the English error report for AIs |
| `bot/deploy/cli.py` | Calls to the official `tgcloud` CLI and parsing of its output |
| `bot/deploy/job.py` | One publication: connect → load ZIP → plan → publish → clean up |
| `bot/main.py`, `bot/ui.py`, `bot/i18n.py` | The Telegram bot (python-telegram-bot), Rich Messages with fallback, Spanish/English texts |
| `examples/hello-bot/` | A complete, valid example project |
| `docs/FORMAT.md` | The project format Builder Hub accepts |
| `prompts/build-for-builder-hub.md` | The prompt to give any AI chat |

Builder Hub pins `@tgcloud/cli@0.2.0`. New CLI versions are tested before the pin is changed.

---

### Español

Builder Hub publica en tu bot de Telegram Serverless el proyecto que te prepare cualquier IA de chat. Mandas el token de acceso de Serverless y el ZIP; el bot lo revisa, te enseña qué cambia (y qué se borraría) y lo sube con el CLI oficial. Tu código no se ejecuta en el servidor de Builder Hub y el token no se guarda. Al terminar, **regenera el token** en @BotFather.

Para **actualizar**, basta con mandarle el ZIP nuevo: enseña las novedades del `CHANGELOG.md` desde la versión publicada y pide confirmación. Guarda todas las versiones (en un canal privado de Telegram si lo configuras en el panel), permite volver a la anterior o a cualquiera con comprobación SHA-256 y **anti-rollback** (`no_rollback_before` en `builderhub.json`), activa solo el botón de menú de la Mini App, pone en cola las publicaciones cuando hay muchas y tiene un módulo de contacto con el propietario. Nunca borra los ZIP del chat.
