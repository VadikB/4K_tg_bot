# TASK-001: каркас учебного Telegram-контура

## Результат

Создан независимый Python-проект с моделью учебных проектов, несколькими ролями
CRISP-DM на участника, версионируемой спецификацией оценки, назначениями и правилом
одного нового кейса в день.

## Область

- Включено: каркас, конфигурация, модель PostgreSQL, Alembic, закрытый API-порт 4К,
  Telegram-команды-заглушки, unit-тесты и документация.
- Не входит: публикация предметных артефактов, production API 4К, полный admin UX,
  реальные приглашения, деплой, токен бота.

## Источники и решения

- `/Users/vadim_bogachev/Developer/4K/README.md`, `CONTRIBUTING.md`.
- `docs/evc/agent-workflow.md`, `verification-matrix.md`, `artifact-recipe.md`.
- `docs/architecture/product-4k/1.0/context.md`, `registry.md`.
- `docs/architecture/product-4k/1.0/updates/2026-10-01/README.md`.
- `docs/methodology/source-sets/2026-10-01/manifest.json`.
- `docs/adr/002-cycle-as-dialogue-contracts.md`, `docs/architecture/assessment-runtime.md`.
- Основание: согласование владельца в чате 06.11.2026.
- Решение: самостоятельная БД, тонкий Telegram-клиент, несколько ролей участника,
  отдельное назначение на роль, один новый кейс в день.
- Пробел: production integration API 4К не утверждён; зависимый HTTP-путь выключен.

Стоп-условия: все `нет`. Существующие данные и API 4К не меняются; новый предметный
артефакт не публикуется; секреты и production-данные не используются; откат —
остановить новый сервис и удалить его отдельную БД/каталог до появления данных.

## Архитектурный адрес

PM-02: ссылка на версию RoleProfile; PM-03/04: внешний Cycle/Case через адаптер.
Бот владеет учебной карточкой и маршрутом, но не Evidence, IA или Results.

## Критерии приёмки

- [x] Системная роль отделена от CRISP-DM-роли.
- [x] Участнику можно назначить несколько версий проектных ролей.
- [x] Назначение фиксирует версии роли и спецификации.
- [x] Дневной лимит учитывает часовой пояс и активный кейс.
- [x] Отключённая интеграция завершается явной ошибкой.
- [x] PostgreSQL-миграция проверена на отдельной локальной БД `4k_tg_bot`.
- [ ] Полные пользовательские сценарии Telegram реализованы.

## Проверки

- `.venv/bin/ruff check .` → PASS.
- `.venv/bin/mypy app` → PASS, 11 файлов.
- `.venv/bin/pytest -q` → PASS, 10 тестов.
- `.venv/bin/python -m compileall -q app migrations tests` → PASS.
- `git diff --check` → PASS.
- `.venv/bin/alembic upgrade head` → PASS, создано 14 таблиц с `alembic_version`.
- `.venv/bin/alembic downgrade base && .venv/bin/alembic upgrade head` → PASS.
- CI / Telegram API / production API 4К → NOT_RUN: нет remote, токена и утверждённого
  интеграционного endpoint; это не блокирует технический каркас, но блокирует пилот.

## Действия выпуска

`branch_push=false`, `pr=false`, `merge=false`, `deploy=false`,
`version_bump=false`, `artifact_publish=false`.

## Откат

До пилотных данных удалить отдельный сервис и volume. После появления данных —
сначала backup, затем выключить бот и сохранить БД для чтения; опубликованные
snapshots и внешние Cycle не удалять.
