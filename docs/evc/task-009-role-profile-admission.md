# TASK-009: проверка роли 4К перед публикацией проектной роли

## Результат

Переход проектной роли `draft -> published` выполняется только после read-only
проверки точных ID/checksum опубликованной RoleProfileVersion в 4К.

## Область

- Включено: HTTP adapter, двухфазная проверка без открытой DB-транзакции,
  повторная сверка mapping под row lock и Telegram error path.
- Не входит: каталог выбора в UI, project assignment snapshot и Cycle.

## Источники и решения

- Серверный контракт: 4К TGBOT-03, ветка `codex/tg-bot-educational-cycle-context`.
- Fallback при отключённой/недоступной интеграции запрещён: роль остаётся draft.
- Внешний HTTP выполняется вне PostgreSQL transaction. Перед публикацией mapping
  блокируется и повторно сравнивается с проверенным ответом.

## Проверки

- Ruff → PASS; mypy → PASS.
- Unit → 34 PASS.
- PostgreSQL integration → 11 PASS.
- `git diff --check` → PASS.
- Реальный сетевой вызов → NOT_RUN до настройки общего `.env`; обе стороны имеют
  совместимые contract tests.

## Действия выпуска

`branch_push=false`, `pr=false`, `merge=false`, `deploy=false`,
`version_bump=false`, `artifact_publish=false`.

## Откат

Отключить команду публикации роли. Уже published версии не переписывать; удаление
проверки само по себе не является допустимым fallback.
