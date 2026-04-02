# SmartLife в Portainer

Этот сценарий нужен для переноса проекта в **Portainer Stack из Git-репозитория** без ручной подготовки `secrets/` на сервере.

## Что изменено для Portainer

- добавлен `docker-compose.portainer.yml`;
- добавлен `stack.env.portainer.example`;
- `SMARTLIFE_APP_IMAGE` больше не используется: Portainer собирает `app` напрямую из Git-репозитория, чтобы новые релизы не залипали на старом image tag;
- приложение умеет читать ключ приложения и пароль БД не только из файлов в `secrets/`, но и из переменных окружения:
  - `SMARTLIFE_APP_SECRET_KEY`
  - `SMARTLIFE_DB_PASSWORD`
- cloud-настройки Tuya, как и раньше, живут в PostgreSQL и не требуют файловых secrets.

## Рекомендуемый сценарий развёртывания

### 1. Подготовить значения для Portainer

Обязательные переменные:

- `SMARTLIFE_APP_SECRET_KEY`
- `SMARTLIFE_DB_PASSWORD`
- `SMARTLIFE_APP_BASE_URL`
- `SMARTLIFE_PUBLIC_PORT`

Переменная `SMARTLIFE_APP_IMAGE` больше не нужна.

Минимально рекомендуемые:

- `SMARTLIFE_STACK_NAME=smartlife`
- `SMARTLIFE_PROVIDER=demo`
- `SMARTLIFE_TIMEZONE=Europe/Moscow`
- `SMARTLIFE_BACKGROUND_SYNC_ENABLED=yes`
- `SMARTLIFE_SYNC_ON_STARTUP=yes`

### 2. Создать Stack в Portainer

Источник:
- **Repository**
- ветка: `main`
- compose file path: `docker-compose.portainer.yml`

Environment variables:
- взять из `stack.env.portainer.example`;
- реальные секреты задать в Portainer вручную.

### 3. Проверить после первого запуска

Открыть:
- `http://<IP_или_DNS>:<SMARTLIFE_PUBLIC_PORT>/health`

Проверить внутри контейнера:
- версия приложения;
- доступность БД;
- volume `*_backups` для дампов.

## Где теперь живут данные

Portainer stack использует named volumes:

- `${SMARTLIFE_STACK_NAME}_postgres_data`
- `${SMARTLIFE_STACK_NAME}_backups`

Это удобно для Git-deploy через Portainer: данные не завязаны на относительные bind-mount пути проекта.

## Что важно

- `docker-compose.yml` и `scripts/manage.sh` остаются рабочими для обычного git/ssh сценария;
- `docker-compose.portainer.yml` — отдельный compose именно под Portainer;
- если нужно перенести существующие дампы, их потом можно копировать в named volume backups или восстановить через UI/команду после первого запуска.


## Перенос существующей базы из текущего docker-compose стенда

Перед переключением на Portainer:

1. На старом стенде сделать дамп:

```bash
cd /opt/SmartLife
./scripts/manage.sh backup-db
./scripts/manage.sh backup-list
```

2. Развернуть новый Stack в Portainer из `docker-compose.portainer.yml`.

3. После первого запуска загрузить последний `.dump` в UI SmartLife через раздел **Резервные копии** или положить файл в volume backups и восстановить его уже из интерфейса.

Для копирования дампа в named volume backups можно использовать одноразовый контейнер:

```bash
docker run --rm   -v smartlife_backups:/target   -v /opt/SmartLife/backups:/source:ro   alpine sh -lc 'mkdir -p /target/db && cp -av /source/db/*.dump /target/db/'
```

Если имя volume отличается, использовать фактическое имя `${SMARTLIFE_STACK_NAME}_backups`.


## Что поменялось в v0.11.23

- Portainer-стек больше не использует `SMARTLIFE_APP_IMAGE`;
- сервис `app` собирается из Git через `build`, поэтому при redeploy stack подтягивается текущий код репозитория;
- это уменьшает риск зависнуть на старом image tag после нового релиза.


## Обновление v0.11.24

- healthcheck для сервиса `app` переведён на лёгкий `GET /favicon.ico`, поэтому Portainer больше не должен дёргать тяжёлый `/health` во время ручного получения `local key` и `LAN-probe`;
- после успешного `LAN-probe` SmartLife больше не включает молча `Предпочитать LAN`; финальную политику (`LAN-профиль`, `prefer LAN`) пользователь сохраняет сам.


## Обновление v0.11.25

- список `Устройства` теперь показывает LAN-инвентаризацию по каждому устройству: локальный IP, MAC и явные метки локального статуса;
- MAC сохраняется после ручного запроса `Получить key/IP из Tuya вручную и проверить LAN`, поэтому проход по устройствам можно делать без лишних повторных cloud-запросов;
- это помогает по-человечески видеть, где key уже получен, где LAN-профиль включён и какие устройства уже переведены в локальный режим.


## Обновление v0.11.26

- на странице `Синхронизация` появился полноценный JSON-резерв LAN-профилей: его можно скачать, сохранить в volume backups и потом импортировать обратно без повторного прохода по Tuya;
- backup включает `external_id`, локальный IP, `protocol version`, `local_key`, MAC, флаги `LAN enabled` / `prefer LAN` и результат последнего probe;
- MAC теперь пытается подбираться не только из payload Tuya, но и локально через ARP/neighbor cache после успешного LAN-probe, поэтому повторный расход Tuya quota ради MAC не требуется;
- в отдельные будущие задачи вынесен перевод Stack/контейнеров SmartLife на non-root режим в Portainer.
