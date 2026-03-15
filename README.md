# SmartLife

SmartLife — веб-приложение для управления устройствами Smart Life / Mi Home, просмотра статусов и расчёта энергопотребления за день и месяц.

Стек:
- Python 3.12
- FastAPI + Jinja2
- PostgreSQL
- Docker Compose

## Что уже есть в `v0.3.1`

- LAN-first запуск с выбором IP и порта;
- изолированное Docker-окружение;
- секреты только в `./secrets`, а не в `.env`;
- demo-провайдер для быстрого старта;
- рабочая интеграция **Tuya Cloud**;
- импорт списка устройств из cloud project;
- опрос живых статусов (`switch_1`, `add_ele`, `cur_power`, `cur_voltage`, `cur_current`, `fault`);
- накопление снапшотов статуса в PostgreSQL;
- расчёт расхода **за день** и **за месяц** по счётчику `add_ele` без платного Power Management;
- автоматическая фоновая синхронизация по расписанию;
- журнал последних циклов синхронизации в UI и API;
- иконка проекта, favicon, manifest и root-маршруты для иконок;
- версия ПО в футере на всех страницах;
- веб-панель с живыми метриками и историей снапшотов;
- сводная панель с топ-потребителями и устройствами, которые сейчас тянут нагрузку;
- графики расхода по дням и график мощности на карточке устройства;
- JSON API по устройствам, энергостатистике, снапшотам и синхронизации.

## Быстрый старт

### Новый сервер / чистое развёртывание

```bash
git clone https://github.com/messireL/SmartLife.git /opt/SmartLife
cd /opt/SmartLife
chmod +x scripts/manage.sh
./scripts/manage.sh up --build
./scripts/manage.sh seed-demo
./scripts/manage.sh rebuild-energy
./scripts/manage.sh health
./scripts/manage.sh url
```

При первом запуске скрипт сам:
- создаст `.env` из шаблона;
- создаст каталог `secrets/`;
- сгенерирует `secrets/app_secret_key` и `secrets/db_password`;
- создаст пустые файлы для Tuya / Xiaomi секретов;
- предложит выбрать IP-адрес из найденных на сервере;
- по умолчанию отдаст приоритет адресу из `192.168.x.x`;
- предложит порт публикации (по умолчанию `13443`).

## Где лежат секреты

Секреты не хранятся в `.env`. Они лежат в:

```text
/opt/SmartLife/secrets/
```

Основные файлы:
- `app_secret_key`
- `db_password`
- `smartlife_tuya_access_id`
- `smartlife_tuya_access_secret`
- `smartlife_tuya_project_code`
- `smartlife_xiaomi_username`
- `smartlife_xiaomi_password`
- `smartlife_xiaomi_device_token`

## Подключение Tuya Cloud

1. На Tuya Developer Platform привяжи Smart Life app account к проекту.
2. Подготовь `Access ID` и `Access Secret` проекта.
3. Выполни:

```bash
cd /opt/SmartLife
./scripts/manage.sh configure-tuya
```

Скрипт:
- предложит региональный `OpenAPI` endpoint;
- попросит `Access ID` и `Access Secret`;
- сохранит ключи в `secrets/`;
- переключит `SMARTLIFE_PROVIDER=tuya_cloud`.

После этого:

```bash
./scripts/manage.sh configure-sync
./scripts/manage.sh configure-timezone Europe/Moscow
./scripts/manage.sh up --build
./scripts/manage.sh health
./scripts/manage.sh url
```

Ручной запуск синхронизации по-прежнему доступен:

```bash
./scripts/manage.sh sync
```

## Как считается энергопотребление

Для Tuya используется накопительный счётчик `add_ele`.

Логика:
- каждый опрос сохраняет снапшот статуса;
- из `add_ele` берётся `energy_total_kwh`;
- расход = положительная разница между новым и предыдущим снапшотом;
- день = сумма дельт за текущие сутки;
- месяц = сумма дельт за текущий месяц.

Если счётчик сбросился назад, отрицательная дельта не учитывается — это защита от перепривязки, сброса устройства или туевской внезапной философии.

## LAN-настройка

Несекретные параметры сети лежат в `.env`:

```env
SMARTLIFE_NETWORK_MODE=lan
SMARTLIFE_LAN_ONLY=yes
SMARTLIFE_LAN_SUBNET_PREFIX=192.168.
SMARTLIFE_BIND_IP=192.168.1.50
SMARTLIFE_PUBLIC_PORT=13443
SMARTLIFE_APP_BASE_URL=http://192.168.1.50:13443
SMARTLIFE_PROVIDER=tuya_cloud
SMARTLIFE_TUYA_BASE_URL=https://openapi.tuyaeu.com
SMARTLIFE_SYNC_INTERVAL_SECONDS=60
SMARTLIFE_BACKGROUND_SYNC_ENABLED=yes
SMARTLIFE_SYNC_ON_STARTUP=yes
```

Если нужно перенастроить адрес/порт:

```bash
./scripts/manage.sh configure
```

Если нужно перенастроить фоновые циклы:

```bash
./scripts/manage.sh configure-sync
./scripts/manage.sh configure-timezone Europe/Moscow
```

Если нужно сменить часовой пояс приложения:

```bash
./scripts/manage.sh configure-timezone Europe/Moscow
```

Если нужно пересчитать исторические day/month агрегаты из уже накопленных снапшотов:

```bash
./scripts/manage.sh rebuild-energy
```

## Управление

```bash
./scripts/manage.sh configure
./scripts/manage.sh configure-tuya
./scripts/manage.sh configure-demo
./scripts/manage.sh configure-sync
./scripts/manage.sh configure-timezone Europe/Moscow
./scripts/manage.sh up --build
./scripts/manage.sh sync
./scripts/manage.sh seed-demo
./scripts/manage.sh rebuild-energy
./scripts/manage.sh down
./scripts/manage.sh logs
./scripts/manage.sh shell
./scripts/manage.sh health
./scripts/manage.sh url
```

## Что ещё не реализовано

- управление устройствами (toggle / send commands);
- полноценная Xiaomi / Mi Home интеграция;
- фильтры по комнатам и типам устройств;
- multi-user и роли.

## Трансфер в новый чат

Актуальное состояние проекта поддерживается в файле:

`docs/TRANSFER_TO_NEW_CHAT.md`


Обновление сервера через git:

```bash
cd /opt/SmartLife
git pull --ff-only
chmod +x scripts/manage.sh
./scripts/manage.sh up --build
./scripts/manage.sh health
./scripts/manage.sh url
```


Примечание по версии и времени
- версия UI и `/health` берётся из кода релиза, а не из `.env`;
- хранение времени остаётся в UTC, но UI и агрегаты дня/месяца используют `SMARTLIFE_TIMEZONE` (по умолчанию `Europe/Moscow`).
