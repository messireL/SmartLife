# SmartLife — пакет для переноса в новый чат

В этот пакет для нового чата входят:

- `docs/TRANSFER_TO_NEW_CHAT.md` — полный контекст проекта и хронология релизов;
- `docs/PORTAINER.md` — как сейчас разворачивать проект через Portainer;
- `docs/SERVER_COMMANDS.md` — полезные команды для текущего git/ssh и Portainer-сценария;
- `stack.env.portainer.example` — шаблон env для Portainer Stack;
- `docker-compose.portainer.yml` — актуальный Portainer compose.

## Что важно сообщить в новом чате

- текущая точка после этого релиза: `v0.11.23`;
- Portainer-стек больше не должен зависеть от `SMARTLIFE_APP_IMAGE`;
- при переносе существующей БД нужно использовать те же `APP_SECRET_KEY` и `DB_PASSWORD`;
- если Tuya Billing ещё не ожил, список устройств на новом пустом стенде не подтянется из облака автоматически;
- cloud-режим лучше держать в `Ручной`, чтобы не тратить лимит при его восстановлении.
