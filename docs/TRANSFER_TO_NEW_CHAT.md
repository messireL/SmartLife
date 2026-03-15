# SmartLife — сообщение для нового чата

Проект: SmartLife — веб-приложение управления устройствами Smart Life / Mi Home  
Репозиторий: https://github.com/messireL/SmartLife  
Путь на сервере: /opt/SmartLife  
Стек: Python + FastAPI + PostgreSQL + Docker Compose  
Пуш в GitHub: через локальный ПК / GitHub Desktop

## Как работаем

Ты всегда отвечаешь в таком порядке:

1. дистрибутив архивом  
2. commit message отдельно в окне кода, без команды `git commit`  
3. команды для сервера отдельно в окне кода  
4. в каждом релизе обязательно обновляешь этот файл `docs/TRANSFER_TO_NEW_CHAT.md`

## Текущее состояние

Версия: `v0.5.0`

Сделано:
- LAN-first запуск с привязкой к локальному IP и порту по умолчанию `13443`;
- изоляция Docker-окружения и секреты только в `secrets/`;
- рабочая интеграция `tuya_cloud` и demo-провайдер для быстрого старта;
- импорт устройств, live-статусы, снапшоты и расчёт day/month расхода по `add_ele`;
- фоновая синхронизация по расписанию;
- UI с разделами **Главная / Устройства / Комнаты / Потребление / Синхронизация / Настройки / Резервные копии**;
- карточка устройства с вкладками **Обзор / Графики / История / Управление**;
- формат времени в UI: `ДД-ММ-ГГГГ ЧЧ:ММ:СС`;
- дефолтный часовой пояс `Europe/Moscow`;
- базовое управление Tuya-розетками через `switch_1`;
- журнал команд устройству;
- скрытие temp-устройств по умолчанию и ручное скрытие/возврат устройств из UI;
- автоматическая очистка устройств провайдера `demo` при работе не в demo-режиме и команда `cleanup-demo`;
- при синхронизации удаляются из локальной БД устройства текущего провайдера, которых больше нет в источнике;
- автобэкап БД перед `restart` и `up --build`;
- команды `backup-db`, `backup-list`, `restore-db`;
- локальные `имя / комната / заметки` для устройств, которые не перетираются синхронизацией;
- фильтры по провайдеру и комнате;
- массовые действия на странице устройств: скрыть, показать, назначить комнату, очистить локальную комнату;
- раздел **Комнаты** со сводкой по помещениям;
- favicon, icon и manifest.

## Важные детали

### Обновление сервера

Используем **только git workflow**:

```bash
cd /opt/SmartLife
git pull --ff-only
chmod +x scripts/manage.sh
./scripts/manage.sh up --build
./scripts/manage.sh health
./scripts/manage.sh url
```

Архив релиза не накатывается поверх git-репозитория как основной путь обновления.

Если на сервере остались локальные изменения и `git pull` упёрся:

```bash
cd /opt/SmartLife
git reset --hard HEAD
git pull --ff-only
chmod +x scripts/manage.sh
./scripts/manage.sh up --build
./scripts/manage.sh health
./scripts/manage.sh url
```

### База данных

Автобэкап делается перед:
- `./scripts/manage.sh restart`
- `./scripts/manage.sh up --build`

Ручные команды:

```bash
./scripts/manage.sh backup-db
./scripts/manage.sh backup-list
./scripts/manage.sh restore-db backups/db/<file>.dump
./scripts/manage.sh cleanup-demo
```

Автовосстановление намеренно не включено, чтобы не откатывать базу без явной команды.

### Tuya

Проверенная модель розетки уже отдаёт:
- `switch_1`
- `add_ele`
- `cur_current`
- `cur_power`
- `cur_voltage`
- `fault`

Нормализация значений:
- `add_ele / 1000` → `kWh`
- `cur_power / 10` → `W`
- `cur_voltage / 10` → `V`
- `cur_current / 1000` → `A`

Управление в текущем релизе:
- поддержан базовый toggle через `switch_1`;
- статус команды пишется в `device_command_logs`.

### Часовой пояс

- UI и day/month агрегаты используют `SMARTLIFE_TIMEZONE`;
- текущее значение по умолчанию: `Europe/Moscow`.

## Полезные команды

### Новый сервер

```bash
cd /opt
git clone https://github.com/messireL/SmartLife.git SmartLife
cd /opt/SmartLife
chmod +x scripts/manage.sh
./scripts/manage.sh up --build
./scripts/manage.sh configure-tuya
./scripts/manage.sh configure-sync
./scripts/manage.sh configure-timezone Europe/Moscow
./scripts/manage.sh health
./scripts/manage.sh url
```

### Уже развёрнутый сервер

```bash
cd /opt/SmartLife
git pull --ff-only
chmod +x scripts/manage.sh
./scripts/manage.sh configure-tuya
./scripts/manage.sh configure-sync
./scripts/manage.sh configure-timezone Europe/Moscow
./scripts/manage.sh up --build
./scripts/manage.sh rebuild-energy
./scripts/manage.sh health
./scripts/manage.sh url
```

## Следующие логичные шаги

1. расширенное управление устройствами beyond `switch_1`;  
2. полноценная Xiaomi / Mi Home интеграция;  
3. автообновление через JS без полного reload страницы;  
4. сценарии / расписания / уведомления;  
5. multi-user и роли.

## Подсказка для следующего чата

Если продолжаем разработку, сначала сверяем фактическое состояние `repo/main` и сервера `/opt/SmartLife`, потом готовим следующий релиз.


## Последний релиз
- v0.5.1 — исправление 500 на главной/комнатах, когда в комнате не оставалось видимых устройств.
- v0.5.3 — исправление миграции БД: добавлен столбец `devices.notes`, из-за отсутствия которого на существующей PostgreSQL базе страницы могли падать с Internal Server Error после релиза v0.5.x.
