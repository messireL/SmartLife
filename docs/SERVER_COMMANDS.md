# SmartLife — серверные команды

Этот файл обновляется в каждом релизе и хранит базовые команды для сервера `/opt/SmartLife`.

## Обновление уже развёрнутого сервера

```bash
cd /opt/SmartLife
git reset --hard HEAD
git pull --ff-only
chmod +x scripts/manage.sh
./scripts/manage.sh up --build
./scripts/manage.sh health
./scripts/manage.sh url
```

## Новый сервер

```bash
cd /opt
git clone https://github.com/messireL/SmartLife.git SmartLife
cd /opt/SmartLife
chmod +x scripts/manage.sh
./scripts/manage.sh up --build
./scripts/manage.sh health
./scripts/manage.sh url
```

## Настройка Tuya Cloud

```bash
cd /opt/SmartLife
./scripts/manage.sh configure-tuya
./scripts/manage.sh configure-sync
./scripts/manage.sh configure-timezone Europe/Moscow
./scripts/manage.sh up --build
./scripts/manage.sh cleanup-demo
./scripts/manage.sh health
./scripts/manage.sh url
```

## Резервные копии

```bash
./scripts/manage.sh backup-db
./scripts/manage.sh backup-list
./scripts/manage.sh restore-db backups/db/<file>.dump
```

## Служебные команды

```bash
./scripts/manage.sh sync
./scripts/manage.sh rebuild-energy
./scripts/manage.sh cleanup-demo
./scripts/manage.sh logs
./scripts/manage.sh shell
```

## Что делает manage.sh перед запуском

- очищает экран `clear`;
- удаляет остановленные ненужные Docker-контейнеры через `docker container prune -f`;
- затем выполняет выбранную команду SmartLife.
