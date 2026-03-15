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

## Что уже сделано в текущем состоянии

Версия: `v0.2.2`

Сделано:
- стартовый MVP-каркас FastAPI + PostgreSQL + Docker Compose;
- изоляция Docker-окружения через отдельный compose project name, volume и network;
- секреты вынесены из `.env` в файловую директорию `secrets/`;
- LAN-first мастер первого запуска с приоритетом адресов `192.168.x.x` и портом по умолчанию `13443`;
- режим `LAN-only`, не позволяющий случайно публиковать сервис на `0.0.0.0`;
- demo-провайдер с тестовыми устройствами и метриками;
- рабочая интеграция `tuya_cloud`;
- импорт списка устройств из Tuya cloud project через `GET /v2.0/cloud/thing/device`;
- чтение спецификации устройства через `GET /v1.0/iot-03/devices/{device_id}/specification`;
- чтение текущего статуса через `GET /v1.0/iot-03/devices/{device_id}/status`;
- сохранение живых снапшотов статуса в таблицу `device_status_snapshots`;
- сохранение текущих live-метрик прямо в карточке устройства (`switch_on`, `current_power_w`, `current_voltage_v`, `current_a`, `energy_total_kwh`, `fault_code`);
- расчёт суточного и месячного расхода по счётчику `add_ele` на своей стороне без Tuya Power Management;
- фоновый планировщик синхронизации по расписанию внутри приложения;
- журнал синхронизаций в UI и API (`/api/sync/status`, `/api/sync/runs`);
- команда `./scripts/manage.sh configure-sync` для настройки интервала и поведения фонового цикла;
- иконка проекта и favicon в `app/static/`;
- веб-панель со списком устройств, live-статусами, суммарной нагрузкой и историей снапшотов.

## Текущее поведение

Сейчас проект умеет работать в двух режимах:

### 1. `SMARTLIFE_PROVIDER=demo`
- быстрый запуск без реальных устройств;
- загрузка demo-устройств и истории энергометрик;
- проверка UI, API и расчётов.

### 2. `SMARTLIFE_PROVIDER=tuya_cloud`
- чтение Tuya Access ID / Access Secret из `secrets/`;
- запрос access token;
- импорт устройств из проекта Tuya;
- чтение live-статусов розеток и других устройств;
- накопление снапшотов и расчёт day/month по `add_ele`;
- автоматическая фоновая синхронизация при старте и далее по интервалу.

## Важные детали по Tuya

Проверенная модель розетки уже отдаёт нужные поля:
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

Логика расчёта расхода:
- каждый sync сохраняет новый снапшот;
- берётся разница `energy_total_kwh` между новым и предыдущим снапшотом;
- в day/month идёт только положительная дельта;
- если счётчик сбросился назад, отрицательная дельта игнорируется.

## Что важно помнить дальше

Следующие крупные шаги:
1. графики по мощности и потреблению;
2. фильтры по комнатам/типам устройств;
3. управление устройствами (toggle / команды);
4. полноценная интеграция Xiaomi Mi Home / miIO;
5. расширенный roadmap по Smart Life / Mi Home устройствам и аналитике;
6. при желании — отдельный экран настроек интеграции и синхронизации в самом UI.

## Полезные команды на сервере

### Новый сервер

```bash
cd /opt
git clone https://github.com/messireL/SmartLife.git SmartLife
cd /opt/SmartLife
chmod +x scripts/manage.sh
./scripts/manage.sh up --build
./scripts/manage.sh configure-tuya
./scripts/manage.sh configure-sync
./scripts/manage.sh restart
./scripts/manage.sh health
./scripts/manage.sh url
```

### Уже развёрнутый сервер

```bash
cd /opt/SmartLife
chmod +x scripts/manage.sh
./scripts/manage.sh configure-tuya
./scripts/manage.sh configure-sync
./scripts/manage.sh up --build
./scripts/manage.sh health
./scripts/manage.sh url
```

## Подсказка для следующего чата

Если продолжаем разработку, сначала сверяем фактическое состояние `repo/main` и сервера `/opt/SmartLife`, потом готовим следующий релиз.
