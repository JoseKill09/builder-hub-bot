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

## Security model

- **Your code never runs on the Builder Hub server.** It is only validated and uploaded; it runs on Telegram's infrastructure, inside your bot.
- **Tokens are never stored or logged.** The token lives in memory for the duration of one publication, is passed to the CLI only through an environment variable, and is masked in every log line. The message where you sent it is deleted immediately.
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
git clone https://github.com/JoseKill09/builder-hub-bot && cd builder-hub
cp .env.example .env           # then fill BOT_TOKEN and ADMIN_IDS
docker compose up -d --build
```

| Variable | Meaning |
|---|---|
| `BOT_TOKEN` | Bot API token of *your* Builder Hub bot (from BotFather) |
| `ADMIN_IDS` | Telegram user IDs allowed to open the admin panel (comma-separated) |
| `PUID` / `PGID` | Owner of `./data` on the host (default `1000:10`) |
| `RICH_MESSAGES` | `0` to force classic HTML messages |
| `MAX_PARALLEL` | Publications at the same time (default 2) |
| `JOB_TTL` | Seconds before an unfinished publication is cancelled and forgotten (default 900) |

Runtime settings (sign-ups open/closed, max ZIP size, daily limit per user, blocked users) are changed from the **🛡 Panel** inside the bot.

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
