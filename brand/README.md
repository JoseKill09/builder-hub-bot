# Builder Hub — brand

| File | Use |
|---|---|
| `logo.svg` | Logo (vector). An open box (the ZIP) with an arrow going up (publish). Safe for Telegram's circular crop. |
| `profile.jpg` | Bot profile photo, 640×640. Set it from the bot: 🛡 Panel → 🎨 Bot profile (`setMyProfilePhoto`). |
| `logo-640.png` | Logo as PNG. |
| `logo-circulo.png` | Preview with the circular crop, light and dark. |
| `banner-es-640x360.png`, `banner-en-640x360.png` | "Description picture" (shown in an empty chat). Only @BotFather can set it: /mybots → bot → Edit Bot → Edit Description Picture. |
| `banner-*.html`, `profile.html`, `circulo.html`, `render.py` | Sources; `render.py` regenerates the images with Playwright. |

Colours: `#FF8A3D` → `#F0436A` (gradient), text `#1B1416`, background `#FBF6F2`. Fonts: Fraunces (title), Inter (text).

## Texts (set automatically by the bot at start-up, in Spanish and English)

- **Name:** Builder Hub
- **Slogan:** *Ship your Telegram Serverless bot from any AI chat.* / *Publica tu bot de Telegram Serverless desde cualquier IA.*
- **Short description / About** and **Description**: see `bot/brand.py` (`SHORT`, `DESCRIPTION`).
- **Commands:** /start, /projects, /prompt, /contact, /help, /cancel.
