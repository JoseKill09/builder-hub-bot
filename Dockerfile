# Builder Hub: Python (bot) + Node (CLI oficial de Telegram Serverless). El código de los usuarios NO se ejecuta aquí:
# solo se revisa y se sube a la nube de Telegram con `tgcloud push`.
FROM node:22-slim AS node

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 NPM_CONFIG_UPDATE_NOTIFIER=false

# Node 22 (para `node --check` y el CLI) copiado de la imagen oficial
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && npm install -g --ignore-scripts @tgcloud/cli@0.2.0 \
 && npm cache clean --force \
 && tgcloud --version

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
COPY tests ./tests
COPY examples ./examples
COPY prompts ./prompts

# Usuario sin privilegios
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin builder-hub
USER builder-hub

CMD ["python", "-m", "bot.main"]
