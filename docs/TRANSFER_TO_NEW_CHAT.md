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

Версия: `v0.4.0`

Сделано:
- LAN-first запуск с привязкой к локальному IP и порту по умолчанию `13443`;
- изоляция Docker-окружения и секреты только в `secrets/`;
- demo-провайдер и рабочая интеграция `tuya_cloud`;
- импорт устройств из Tuya, получение спецификации и live-статусов;
- хранение снапшотов статуса в PostgreSQL;
- расчёт day/month расхода по счётчику `add_ele` без Tuya Power Management;
- фоновая синхронизация по расписанию;
- UI с разделами **Главная / Устройства / Потребление / Синхронизация / Настройки / Резервные копии**;
- вкладки на карточке устройства **Обзор / Графики / История / Управление**;
- графики мощности и расхода;
- формат времени в UI: `ДД-ММ-ГГГГ ЧЧ:ММ:СС`;
- дефолтный часовой пояс `Europe/Moscow`;
- базовое управление Tuya-розетками через `switch_1`;
- журнал команд устройству;
- скрытие temp-устройств по умолчанию и ручное скрытие/возврат устройств из UI;
- при синхронизации удаляются из локальной БД устройства текущего провайдера, которых больше нет в источнике;
- автобэкап БД перед `restart` и `up --build`;
- команды `backup-db`, `backup-list`, `restore-db`;
- иконка проекта, favicon и manifest.

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

### База данных

Автобэкап делается перед:
- `./scripts/manage.sh restart`
- `./scripts/manage.sh up --build`

Ручные команды:

```bash
./scripts/manage.sh backup-db
./scripts/manage.sh backup-list
./scripts/manage.sh restore-db backups/db/<file>.dump
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

1. автообновление страниц в браузере без ручного F5;  
2. расширенное управление устройствами beyond `switch_1`;  
3. полноценная Xiaomi / Mi Home интеграция;  
4. фильтры по комнатам и типам устройств;  
5. multi-user и роли.

## Подсказка для следующего чата

Если продолжаем разработку, сначала сверяем фактическое состояние `repo/main` и сервера `/opt/SmartLife`, потом готовим следующий релиз.
