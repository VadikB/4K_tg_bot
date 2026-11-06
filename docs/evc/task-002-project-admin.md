# TASK-002: административная карточка проекта

## Результат

Bootstrap-администратор создаёт карточку проекта в Telegram и просматривает список.
Данные сохраняются в отдельной PostgreSQL, операция авторизуется и аудируется.

## Область

- Включено: регистрация Telegram identity, bootstrap admin, FSM создания карточки,
  проверка прав, кода, дат и timezone, список доступных проектов, audit event.
- Не входит: участники, приглашения, роли, спецификация оценки и API 4К.

## Источники и решения

Повторно использованы источники TASK-001 и согласованная карточка проекта. Base commit:
`760a7b57658ded714f6346b218940854d796e4a1`. Владелец продукта разрешил продолжение
сообщением «идем дальше» 06.11.2026. Предметные нормы оценки не меняются.

Стоп-условия: все `нет`. Публичный API 4К, существующие данные и артефакты не
затрагиваются. Bootstrap IDs — эксплуатационная конфигурация, секреты не сохраняются.

## Критерии приёмки

- [x] Только администратор может создать проект.
- [x] Проект создаётся пошагово и сохраняет обязательные поля карточки.
- [x] Код нормализуется и остаётся уникальным.
- [x] Даты и IANA timezone валидируются.
- [x] Создание записывает audit event без содержательных текстов проекта.
- [x] Сервисный путь проверен на изолированной PostgreSQL `4k_tg_bot_test`.
- [ ] Telegram polling проверен с реальным токеном.

## Проверки

- `.venv/bin/ruff check .` → PASS.
- `.venv/bin/mypy app` → PASS, 13 source files.
- `.venv/bin/pytest -q -m 'not integration'` → PASS, 15 tests.
- `TEST_DATABASE_URL=postgresql+asyncpg://.../4k_tg_bot_test .venv/bin/pytest -q -m integration`
  → PASS, 2 tests; bootstrap admin/create/audit и participant denial.
- Реальный Telegram polling → NOT_RUN: владелец ещё не передал токен; без этого
  нельзя подтвердить Telegram transport, но application/database path проверен.
- Production API 4К → не применимо к TASK-002.

## Действия выпуска

`branch_push=false`, `pr=false`, `merge=false`, `deploy=false`,
`version_bump=false`, `artifact_publish=false`.

## Откат

Откатить commit TASK-002. Если появились тестовые проекты — сохранить backup и
удалять записи только явной административной операцией; автоматического purge нет.
