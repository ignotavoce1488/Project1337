# Docker на VPS: обновление и проверка веток

Рабочая копия находится в `/opt/project1337`, Compose project называется
`dictaphone_bot`, nginx направляет домен на `127.0.0.1:18000`. Во всех командах
ниже volumes с базой и аудио сохраняются. Не использовать `docker compose down -v`.

## Обновить production до `main`

```sh
cd /opt/project1337
git fetch origin --prune
git switch main
git pull --ff-only origin main

export APP_VERSION=main-$(git rev-parse --short=12 HEAD)
docker build -t slovech:$APP_VERSION .
docker compose -p dictaphone_bot -f compose.yaml -f deploy/compose.vps.yaml \
  up -d --no-build --remove-orphans

docker compose -p dictaphone_bot -f compose.yaml -f deploy/compose.vps.yaml ps
curl --fail https://64-188-60-202.sslip.io/ready
docker compose -p dictaphone_bot -f compose.yaml -f deploy/compose.vps.yaml \
  logs --tail=100 api bot worker
```

Образ собирается один раз и используется всеми тремя сервисами. Если обновление
не прошло, прежний неизменяемый тег можно снова указать в `APP_VERSION` и
повторить `up -d --no-build`. Перед изменениями базы нужен backup по инструкции
из `docs/operations.md`.

## Проверить API и Mini App из другой ветки

Preview изолирован от production: у него отдельные volumes, сеть и порт. Telegram-
бот и worker не запускаются, чтобы два процесса не читали один `BOT_TOKEN`.

```sh
cd /opt/project1337
git fetch origin --prune
git worktree add --detach /opt/project1337-preview origin/ИМЯ_ВЕТКИ
cp .env /opt/project1337-preview/.env
cd /opt/project1337-preview

export APP_VERSION=preview-$(git rev-parse --short=12 HEAD)
docker build -t slovech:$APP_VERSION .
PREVIEW_PORT=18001 APP_VERSION=$APP_VERSION docker compose \
  -p slovech_preview -f compose.yaml -f /opt/project1337/deploy/compose.preview.yaml \
  up -d --no-build api
curl --fail http://127.0.0.1:18001/ready
```

Чтобы открыть preview на своём компьютере, создать SSH-туннель и перейти на
`http://localhost:18001/app`:

```sh
ssh -L 18001:127.0.0.1:18001 root@64.188.60.202
```

Остановить preview и удалить только его тестовые volumes:

```sh
cd /opt/project1337-preview
docker compose -p slovech_preview -f compose.yaml \
  -f /opt/project1337/deploy/compose.preview.yaml down -v
cd /opt/project1337
git worktree remove /opt/project1337-preview
```

Для полноценного теста Telegram-потока нужен отдельный тестовый бот и его токен.
Нельзя запускать preview-бота с production-токеном одновременно с production.
