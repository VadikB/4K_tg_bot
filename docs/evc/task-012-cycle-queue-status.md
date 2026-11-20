# TASK-012: состояния очереди подготовки Cycle

## Результат

Команда `/prepare_cycle ASSIGNMENT_ID` различает три серверных состояния:
`awaiting_admission`, `preparing` и `prepared`. Для `preparing` бот показывает
operation ID и предлагает повторную проверку; `external_cycle_id` сохраняется только
после фактического `prepared`.

## Границы

- Включено: Telegram-представление состояния канонической очереди 4К.
- Не входит: фоновый polling, автоматические уведомления и запуск первого Case.
- Серверный контракт: TGBOT-05, commit следует в ветке
  `codex/tg-bot-educational-cycle-context`.

## Проверки

- Ruff → PASS; mypy → PASS; unit → 35 PASS.
- PostgreSQL integration не повторялся: модель/миграция не изменялись после
  предыдущих 12 PASS; изменение ограничено представлением ответа Telegram.
- CI → NOT_RUN до push/PR.

## Действия выпуска

`branch_push=false`, `pr=false`, `merge=false`, `deploy=false`,
`version_bump=false`, `artifact_publish=false`.

## Откат

Удалить отдельное сообщение `preparing`; сохранённое runtime-состояние не изменять.
