# Builder Hub project format

A Builder Hub project is a **ZIP file** with a Telegram Serverless project inside: the same layout `npm create @tgcloud/bot` produces, without anything that has to be installed or built.

```
my-bot.zip
└── my-bot/                      ← optional single root folder (it is stripped)
    ├── tgcloud/                 ← REQUIRED: everything the platform runs
    │   ├── schema.js            ← database tables (optional, one file)
    │   ├── handlers/            ← one file per Telegram update type, flat
    │   │   ├── message.js
    │   │   └── callback_query.js
    │   ├── endpoints/           ← functions the Mini App calls, flat (optional)
    │   │   └── getProfile.js
    │   └── lib/                 ← shared code, subfolders allowed (optional)
    │       └── format.js
    ├── tgcloud.jsonc            ← only if there is a Mini App
    ├── webapp/                  ← the Mini App, ALREADY BUILT (any folder name)
    │   └── index.html
    ├── CHANGELOG.md             ← recommended: version history ("what's new")
    ├── builderhub.json          ← optional: name, version, anti-rollback
    └── README.md                ← optional, ignored
```

Limits: ZIP up to **20 MB** (Telegram's download limit for bots), **50 MB** unpacked, **3000** files, **15 MB** per file.

## Rules for `tgcloud/`

1. **Only `.js` files** are deployed. Each one is an **ES module** (`import` / `export`), never CommonJS (`require`, `module.exports`).
2. Allowed places:
   - `tgcloud/schema.js` — the only file allowed directly in `tgcloud/`.
   - `tgcloud/handlers/<type>.js` — `<type>` must be a Telegram update type: `message`, `edited_message`, `channel_post`, `edited_channel_post`, `inline_query`, `chosen_inline_result`, `callback_query`, `shipping_query`, `pre_checkout_query`, `poll`, `poll_answer`, `my_chat_member`, `chat_member`, `chat_join_request`, `chat_boost`, `removed_chat_boost`, `message_reaction`, `message_reaction_count`, `business_connection`, `business_message`, `edited_business_message`, `deleted_business_messages`, `purchased_paid_media`, … (Builder Hub reads the current list from Telegram). No subfolders.
   - `tgcloud/endpoints/<name>.js` — `<name>` like a JavaScript identifier (`getProfile`, `save_item`). No subfolders.
   - `tgcloud/lib/**.js` — any depth.
3. Every handler and endpoint has an **`export default`** async function:
   - handler: `export default async function (payload, ctx) { … }` — `payload` is the update's object (`message`, `callback_query`…); `ctx.update` is the raw update.
   - endpoint: `export default async function (input, ctx) { … }` — `ctx.initData.user` is the verified Telegram user. Refuse with `throw new EndpointError('message', { code: 'X' })`.
4. **Imports** — only these:
   - the SDK: `sdk`, `sdk/db`, `sdk/api`, `sdk/fetch`;
   - your own files by **relative path ending in `.js`** that stays inside `tgcloud/`: `import { x } from '../lib/format.js'`.
   No npm packages, no Node built-ins (`fs`, `path`, `crypto`…), no `process.env`.
5. **Database** (`schema.js`): tables are named exports built with `table()` from `sdk/db`. **No foreign keys** (`.references()` / `foreignKey()` throw). Every query is `await`ed.
6. To delete a table or column, mark it `.deprecated('reason')`. Removing it from `schema.js` does **not** drop it.

## Mini App (optional)

`tgcloud.jsonc` at the root names the **built** folder:

```jsonc
{
  "static": {
    "source": "webapp",
    "headers": [{ "path": "/", "set": { "Cache-Control": "no-store" } }]
  }
}
```

- The folder must contain `index.html` and be **ready to serve** (plain HTML/CSS/JS, or the `dist/` output of a build). Serverless never runs `npm run build`.
- Do not put files under `/api/` (reserved for endpoints).
- Include `<script src="https://telegram.org/js/telegram-web-app.js"></script>` and call endpoints with `Telegram.WebApp.Serverless.call('name', input, (err, result) => …)`.
- The site is served at `https://app<id>.tgcloud.ai/`. If the project has **no** `"static"` key, an already published Mini App is left as it is.

## Versions, "what's new" and going back

Builder Hub keeps every published version of each bot, shows the user what changed before updating, and can go back to an older version. It needs two small files at the root:

**`CHANGELOG.md`** — newest version first, one `## X.Y — date` heading per version:

```markdown
# Changelog

## 1.3 — 2026-11-19
- New: /stats command.
- Fixed: the welcome message was sent twice.

## 1.2 — 2026-11-10
- Faster replies.
```

- **Every new ZIP must raise the version** (`1.2` → `1.3` for small changes, `2.0` for big ones) and add its block at the top. Keep the old blocks: Builder Hub shows the user every block newer than the version their bot has.
- Write the entries for the bot's users, in plain words.

**`builderhub.json`** (optional):

```json
{ "name": "Linux ISO Notifier", "version": "1.3", "no_rollback_before": "1.0" }
```

| Key | Meaning |
|---|---|
| `name` | Name shown in the user's project list (default: the ZIP's folder or file name). |
| `version` | Version of this ZIP (default: the first `## X.Y` of `CHANGELOG.md`). |
| `no_rollback_before` | **Anti-rollback.** The oldest version this one can safely go back to. Set it when this version changes stored data in a way older code can't read (renamed fields, a new JSON format inside a column, moved data between tables…). Builder Hub then refuses to restore anything older and tells the user why. Leave it out when older versions still work with the data. |

Builder Hub also blocks going back when the older schema would need a manual database change, and warns when a version in between deleted data.

## Mini App menu button

If the project has a Mini App, Builder Hub turns on the bot's **menu button** right after publishing (it points to `https://app<id>.tgcloud.ai/`), unless the bot already has a Mini App menu button. The user doesn't need to touch @BotFather for that.

It is still good practice to set it from the bot's own code, so it stays right if the bot is published some other way. Do it once, for example when the owner sends `/start`:

```js
await api.setChatMenuButton({ menu_button: { type: 'web_app', text: 'Open', web_app: { url: 'https://app<id>.tgcloud.ai/' } } });
```

Without `chat_id` it is the default for every user. (Only the *Main Mini App* / direct link `t.me/<bot>/<app>` must be configured in @BotFather; there is no Bot API method for it.)

## What happens on publish

- The cloud ends up **exactly** like the ZIP: modules that exist in the bot but not in the ZIP are **deleted** (Builder Hub lists them before publishing).
- Safe database changes are applied (`migrate --safe`). Changes that delete data are applied only if you confirm them twice.
- Database tables that exist but are not in `schema.js` are left untouched.

## Checklist before zipping

- [ ] `tgcloud/` exists and every handler file name is an update type.
- [ ] Every relative import ends in `.js` and the file exists.
- [ ] No `require`, no npm imports, no `process.env`.
- [ ] Handlers/endpoints have `export default`.
- [ ] `schema.js` has no `.references()`.
- [ ] If there is a Mini App: `tgcloud.jsonc` with `static.source`, and that folder has a built `index.html`.
- [ ] No `node_modules/`, `.tgcloud/`, `.env` (they are ignored anyway).
- [ ] `CHANGELOG.md` has a new `## X.Y — date` block at the top (higher than the previous ZIP).
- [ ] If this version changes stored data so that older versions can't use it: `builderhub.json` with `no_rollback_before`.

A complete valid example: [`examples/hello-bot`](../examples/hello-bot).
