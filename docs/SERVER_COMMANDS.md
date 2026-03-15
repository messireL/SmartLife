# SmartLife — команды для сервера

## Обновление сервера через git
```bash
cd /opt/SmartLife
git reset --hard HEAD
git pull --ff-only
chmod +x scripts/manage.sh
./scripts/manage.sh up
./scripts/manage.sh health
./scripts/manage.sh url
```

`./scripts/manage.sh up` по умолчанию делает rebuild контейнеров. Если когда-нибудь понадобится запуск без rebuild, используй `./scripts/manage.sh up --no-build`.

## Настройка облака Tuya
```bash
cd /opt/SmartLife
./scripts/manage.sh configure-tuya
./scripts/manage.sh up
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


Примечание: manage.sh в новых релизах принудительно убирает COMPOSE_IGNORE_ORPHANS из окружения перед вызовом docker compose, чтобы не конфликтовать с --remove-orphans.


## Обновление v0.8.0
- Добавлен тариф электроэнергии с режимами: единый, двухзонный, трёхзонный.
- Стоимость считается по времени снапшотов и доступна с разбивкой по зонам.
- Настраивается через раздел Настройки в веб-интерфейсе.


## Обновление v0.9.2
- После обновления зайди в Настройки и проверь активный тариф и, при необходимости, план на следующий месяц.
- Разбивка kWh по зонам работает даже при нулевых ценах.
