# SmartLife — команды для сервера

## Обновление сервера через git
```bash
cd /opt/SmartLife
git reset --hard HEAD
git pull --ff-only
chmod +x scripts/manage.sh
./scripts/manage.sh up --build
./scripts/manage.sh health
./scripts/manage.sh url
```

## Настройка облака Tuya
```bash
cd /opt/SmartLife
./scripts/manage.sh configure-tuya
./scripts/manage.sh up --build
./scripts/manage.sh health
./scripts/manage.sh url
```

## Ручная очистка demo-устройств
```bash
cd /opt/SmartLife
./scripts/manage.sh cleanup-demo
```

## Бэкапы
```bash
cd /opt/SmartLife
./scripts/manage.sh backup-db
./scripts/manage.sh backup-list
./scripts/manage.sh restore-db backups/db/<file>.dump
```

## Часовой пояс и пересчёт энергии
```bash
cd /opt/SmartLife
./scripts/manage.sh configure-timezone Europe/Moscow
./scripts/manage.sh rebuild-energy
```

## Ручная docker-cleanup
```bash
cd /opt/SmartLife
./scripts/manage.sh cleanup-docker
```
