# SmartLife — команды для сервера

## Обновление сервера через git
```bash
clear
cd /opt/SmartLife
git reset --hard HEAD
git pull --ff-only
chmod +x scripts/manage.sh
./scripts/manage.sh up
./scripts/manage.sh health
./scripts/manage.sh runtime-info
./scripts/manage.sh url
```

`./scripts/manage.sh up` по умолчанию делает rebuild контейнеров. Если когда-нибудь понадобится запуск без rebuild, используй `./scripts/manage.sh up --no-build`.

## LAN-резерв и локальный контур
```bash
clear
cd /opt/SmartLife
./scripts/manage.sh health
./scripts/manage.sh runtime-info
```

После обновления `v0.11.27` открой раздел **Синхронизация**:
- кнопка **Скачать LAN-резерв JSON** выгружает резерв локальных профилей и `local_key`;
- кнопка **Сохранить LAN-резерв на сервере** складывает тот же JSON в `/app/backups/lan`;
- кнопка **Скачать LAN CSV для правки MAC** выгружает текущую инвентаризацию без секретов, чтобы дописать `local_mac` и импортировать файл обратно;
- импорт JSON восстанавливает локальный контур по `external_id` без новых cloud-запросов к Tuya.

## Настройка облака Tuya
```bash
clear
cd /opt/SmartLife
./scripts/manage.sh configure-tuya
./scripts/manage.sh up
./scripts/manage.sh health
./scripts/manage.sh runtime-info
./scripts/manage.sh url
```

## Бэкапы БД
```bash
clear
cd /opt/SmartLife
./scripts/manage.sh backup-db
./scripts/manage.sh backup-list
./scripts/manage.sh backup-prune [keep_last]
./scripts/manage.sh restore-db backups/db/<file>.dump
```

## Часовой пояс, диагностика и пересчёт энергии
```bash
clear
cd /opt/SmartLife
./scripts/manage.sh configure-timezone Europe/Moscow
./scripts/manage.sh runtime-info
./scripts/manage.sh rebuild-energy
```

## Ручная docker-cleanup
```bash
clear
cd /opt/SmartLife
./scripts/manage.sh cleanup-docker
```

## Что изменилось в v0.11.26
- добавлен JSON-резерв LAN-профилей и ключей на странице `Синхронизация`;
- резерв можно скачать, сохранить на сервере и импортировать обратно без повторного расхода лимита Tuya;
- MAC теперь может подтягиваться после успешного LAN-probe локально, без дополнительного Tuya fetch;
- в будущих задачах зафиксирован отдельный блок перевода Portainer/Docker deployment на non-root режим.

## Что изменилось в v0.11.27
- добавлен рабочий MAC-workflow: ручное поле MAC в карточке устройства и CSV-export/import LAN-инвентаризации на странице `Синхронизация`;
- CSV-импорт теперь понимает колонку `local_mac` / `mac` и не затирает уже сохранённый MAC пустой ячейкой;
- список устройств показывает метку `MAC нужен`, если ключ уже получен, но MAC ещё пустой;
- в будущих задачах зафиксирован отдельный блок перевода Portainer/Docker deployment на non-root режим.


## Что изменилось в v0.11.29
- расход теперь может считаться не только по `energy_total_kwh`, но и по интеграции мощности между локальными снапшотами;
- после обновления полезно сделать `./scripts/manage.sh rebuild-energy`, если хочешь сразу пересчитать уже накопленные локальные снапшоты в дневные и месячные bucket-ы;
- список `Устройства` показывает не только cumulative energy, а расход за сегодня / месяц и источник расчёта (`счётчик устройства` / `расчёт по мощности`).


## Что изменилось в v0.11.33
- обычный `sync` теперь использует уже сохранённую версию Tuya Local протокола и короткий timeout на устройство;
- если устройство после обновления железки/прошивки перестало отвечать локально, сначала запусти ручной `LAN-probe` в карточке устройства, чтобы заново подобрать версию, а потом повтори `./scripts/manage.sh sync`;
- для бойлера уточнён локальный маппинг температур и режима, а измеряющие розетки теперь выделяются отдельным профилем в UI.


## v0.11.34

- Исправлен display/UI-путь бойлера: `fault` теперь читается из `dps[20]`, а `dps[9]` больше не показывается как ошибка.
- Для измеряющей розетки добавлен явный локальный маппинг: `18=ток`, `19=мощность`, `20=напряжение`, `17=счётчик энергии`, `26=fault bitmap`.
- В списке устройств телеметрия розеток теперь видна даже если мощность/ток в моменте нулевые, но напряжение уже есть.
- Подготовлен пакет для переноса в новый чат.


## v0.11.35

```bash
clear
cd /opt/SmartLife
./scripts/manage.sh sync
./scripts/manage.sh health
./scripts/manage.sh runtime-info
```

- после выкладки этого релиза достаточно обычного `sync`: он перечитает локальные LAN-payload и обновит display-state для бойлера и `tdq`-розеток без новых cloud-запросов к Tuya.
