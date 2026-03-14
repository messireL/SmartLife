# SmartLife

SmartLife — стартовый MVP веб-приложения для управления устройствами Smart Life / Mi Home, просмотра списка устройств и метрик энергопотребления за день и месяц.

Стек:
- Python 3.12
- FastAPI + Jinja2
- PostgreSQL
- Docker Compose

## Что уже есть

- веб-интерфейс со сводкой и списком устройств;
- карточка устройства с дневной и месячной статистикой;
- JSON API для списка устройств и энергометрик;
- PostgreSQL-модель устройств и энергосэмплов;
- demo-провайдер для быстрого старта и UX-проверок;
- архитектурный задел под провайдеры Tuya Cloud и Xiaomi Mi Home / miIO.

## Быстрый старт

```bash
cp .env.example .env
./scripts/manage.sh up --build
./scripts/manage.sh seed-demo
```

Открыть:
- UI: `http://localhost:18089/`
- Health: `http://localhost:18089/health`
- API devices: `http://localhost:18089/api/devices`

## Провайдеры

Сейчас по умолчанию используется `SMARTLIFE_PROVIDER=demo`.

Подготовлены классы для следующих сценариев:
- `demo` — тестовые устройства и тестовая энергостатика;
- `tuya_cloud` — каркас для интеграции через Tuya Open API;
- `xiaomi_miio` — каркас для локальной интеграции Xiaomi/Mi Home.

## Важное замечание

Этот релиз — именно фундамент проекта. Реальные логины, токены, подпись запросов и синхронизация с облаком / локальной сетью для конкретных аккаунтов и устройств будут подключаться следующим релизом, когда будет понятен приоритет: Smart Life / Tuya Cloud, Xiaomi Mi Home локально, или оба направления сразу.

## Управление

```bash
./scripts/manage.sh up --build
./scripts/manage.sh down
./scripts/manage.sh logs
./scripts/manage.sh seed-demo
./scripts/manage.sh shell
```

## Трансфер в новый чат

Актуальное состояние проекта поддерживается в файле:

`docs/TRANSFER_TO_NEW_CHAT.md`
