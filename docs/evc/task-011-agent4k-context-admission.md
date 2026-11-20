# TASK-011: передача учебного контекста в admission API 4К

## Результат

Команда `/prepare_cycle ASSIGNMENT_ID` передаёт опубликованный immutable snapshot в
`POST /integration/v1/educational-contexts/prepare`. Бот отдельно хранит изменяемое
состояние операции, причины admission и будущий `cycle_id`, не изменяя snapshot.

## Область

- Включено: HTTP adapter, вызов вне DB transaction, повторная проверка checksum под
  row lock, сохранение `awaiting_admission` и Telegram-представление причин.
- `external_cycle_id` назначения сохраняется только при `status=prepared` и
  непустом `cycle_id`.
- Не входит: администраторский UI устранения причин и запуск первого Case.

## Источники и решения

- Серверный контракт: 4К TGBOT-04, ветка `codex/tg-bot-educational-cycle-context`.
- Snapshot TASK-010 остаётся неизменяемым; runtime-состояние вынесено в
  `AssessmentContextPreparation`.
- При недоступном 4К операция завершается закрытой ошибкой и может быть повторена.

## Проверки

- Ruff → PASS; mypy → PASS.
- Unit → 35 PASS.
- PostgreSQL integration → 12 PASS.
- Alembic `0008 -> 0007 -> head` → PASS.
- Реальный совместный HTTP → NOT_RUN до настройки `.env`; обе стороны имеют
  совместимые contract tests.

## Действия выпуска

`branch_push=false`, `pr=false`, `merge=false`, `deploy=false`,
`version_bump=false`, `artifact_publish=false`.

## Откат

Отключить `/prepare_cycle` и HTTP adapter method. Таблицу состояния можно удалить
миграцией `0008 -> 0007`; immutable snapshot и назначения сохраняются.
