# SmartLife

SmartLife — веб-приложение для управления устройствами Smart Life / Mi Home, просмотра статусов, расхода электроэнергии и базового управления розетками.

Стек:
- Python 3.12
- FastAPI + Jinja2
- PostgreSQL
- Docker Compose

## Что есть в v0.5.0

- LAN-first запуск с выбором IP и порта;
- изолированное Docker-окружение;
- секреты только в `./secrets`, а не в `.env`;
- demo-провайдер для быстрого старта;
- рабочая интеграция **Tuya Cloud**;
- импорт устройств, живые статусы и накопление снапшотов;
- расчёт расхода **за день** и **за месяц** по счётчику `add_ele`;
- автоматическая фоновая синхронизация по расписанию;
- версия в футере, favicon, manifest;
- разнесённый UI с навигацией: **Главная / Устройства / Потребление / Синхронизация / Настройки / Резервные копии**;
- вкладки в карточке устройства: **Обзор / Графики / История / Управление**;
- базовое управление Tuya-розетками через `switch_1`;
- журнал отправленных команд устройству;
- автобэкап PostgreSQL перед `restart` и `up --build`;
- команды `backup-db`, `backup-list`, `restore-db`;
- скрытие temp-устройств по умолчанию и ручное скрытие/возврат устройств из UI;
- автообновление главных страниц и карточек устройств по интервалу фоновой синхронизации;
- автоматическая очистка demo-устройств при работе не в demo-режиме и команда cleanup-demo;
- удаление из БД устройств текущего провайдера, которые больше не приходят с очередной синхронизации;
- локальные имя / комната / заметки для устройств без риска, что sync их перетрёт;
- новый раздел **Комнаты** с краткой сводкой по помещениям;
- фильтры по провайдеру и комнате;
- массовые действия по устройствам: скрыть, показать, назначить комнату, очистить локальную комнату.

## Быстрый старт

### Новый сервер

```bash
cd /opt
git clone https://github.com/messireL/SmartLife.git SmartLife
cd /opt/SmartLife
chmod +x scripts/manage.sh
./scripts/manage.sh up --build
./scripts/manage.sh seed-demo
./scripts/manage.sh health
./scripts/manage.sh url
```

### Обновление уже развёрнутого сервера

```bash
cd /opt/SmartLife
git pull --ff-only
chmod +x scripts/manage.sh
./scripts/manage.sh up --build
./scripts/manage.sh health
./scripts/manage.sh url
```

## Подключение Tuya Cloud

```bash
cd /opt/SmartLife
./scripts/manage.sh configure-tuya
./scripts/manage.sh configure-sync
./scripts/manage.sh configure-timezone Europe/Moscow
./scripts/manage.sh up --build
./scripts/manage.sh health
./scripts/manage.sh url
```

Ручная синхронизация остаётся доступной:

```bash
./scripts/manage.sh sync
```

## Резервные копии базы

Автобэкап создаётся перед:
- `./scripts/manage.sh restart`
- `./scripts/manage.sh up --build`

Ручные команды:

```bash
./scripts/manage.sh backup-db
./scripts/manage.sh backup-list
./scripts/manage.sh restore-db backups/db/<file>.dump
./scripts/manage.sh cleanup-demo
```

Важно:
- автосохранение включено;
- **автовосстановление не включено специально**, чтобы не откатывать базу назад без явной команды.

## Часовой пояс и время

- хранение времени остаётся в UTC;
- UI и day/month агрегаты используют `SMARTLIFE_TIMEZONE`;
- по умолчанию — `Europe/Moscow`;
- формат вывода времени в UI: `ДД-ММ-ГГГГ ЧЧ:ММ:СС`.

## Где лежат секреты

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

## Основные команды

```bash
./scripts/manage.sh configure
./scripts/manage.sh configure-tuya
./scripts/manage.sh configure-demo
./scripts/manage.sh configure-sync
./scripts/manage.sh configure-timezone Europe/Moscow
./scripts/manage.sh up --build
./scripts/manage.sh restart
./scripts/manage.sh sync
./scripts/manage.sh rebuild-energy
./scripts/manage.sh backup-db
./scripts/manage.sh backup-list
./scripts/manage.sh restore-db backups/db/<file>.dump
./scripts/manage.sh cleanup-demo
./scripts/manage.sh down
./scripts/manage.sh logs
./scripts/manage.sh shell
./scripts/manage.sh health
./scripts/manage.sh url
```

## Что ещё не реализовано

- полноценная Xiaomi / Mi Home интеграция;
- расширенное управление устройствами beyond `switch_1`;
- multi-user и роли.

## Трансфер в новый чат

Актуальное состояние проекта поддерживается в файле:

`docs/TRANSFER_TO_NEW_CHAT.md`


## Патч v0.5.2

На существующей PostgreSQL базе добавлена миграция `ALTER TABLE devices ADD COLUMN IF NOT EXISTS notes TEXT`, чтобы релизы v0.5.x не падали с `Internal Server Error` из-за отсутствующего столбца `devices.notes`.


Compatibility note: v0.5.4 adds a broader PostgreSQL schema self-heal on startup for older SmartLife databases.
