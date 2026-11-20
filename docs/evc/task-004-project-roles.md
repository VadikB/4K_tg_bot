# TASK-004: версионируемые CRISP-DM-роли

## Результат

Администратор создаёт draft проектной роли, публикует неизменяемую версию и назначает
одному участнику одну или несколько ролей. Участник читает назначения через `/my_roles`.

## Область

- Включено: JSON definition v1, provenance, checksum, lifecycle draft/published,
  PostgreSQL immutability, множественные назначения и одна primary role.
- Не входит: автоматическое создание RoleProfile в 4К, редактирование draft, retire,
  удаление назначения, спецификация оценки.

## Источники и решения

Повторно использованы источники TASK-001–003, M3/runtime-контекст 4К и решение
владельца «делаем» от 06.11.2026. Base commit
`d78cbc4bc4fa83b9f69b9136f06ead86bb2b9953`.

Описание роли является версионируемым предметным артефактом в PostgreSQL:
`definition_json`, `source_json`, `checksum`. Значения не встроены в Python;
код содержит только схему, техническую валидацию и lifecycle. Публикация в runtime
4К не выполняется и требует отдельного интеграционного контракта.

Стоп-условия: все `нет` для локального учебного контура. Граница PM-02 не меняется:
текущая сущность — источник будущего RoleProfile, но ещё не опубликованный RoleProfile 4К.

## Критерии приёмки

- [x] Draft получает детерминированный checksum и provenance.
- [x] Назначить можно только published-версию.
- [x] Published definition/source/checksum нельзя изменить или удалить.
- [x] У участника может быть несколько ролей и ровно не более одной primary.
- [x] Участник видит точные версии своих ролей.
- [x] Миграция проверена на PostgreSQL.
- [ ] Telegram transport проверен с реальным токеном.
- [ ] Передача роли в RoleProfile 4К реализована.

## Проверки

- `.venv/bin/ruff check .` → PASS.
- `.venv/bin/mypy app` → PASS.
- Unit → PASS, 21 tests.
- PostgreSQL integration → PASS, 6 tests; две роли, primary, participant projection,
  published immutability.
- Alembic existing DB `0002 -> 0003` → PASS.
- Alembic downgrade/upgrade `0003 -> 0002 -> 0003` → PASS.
- Fresh migration `base -> 0001 -> 0002 -> 0003` → PASS.
- Telegram/API 4К → NOT_RUN: токен и утверждённый endpoint отсутствуют.

## Действия выпуска

`branch_push=false`, `pr=false`, `merge=false`, `deploy=false`,
`version_bump=false`, `artifact_publish=false`.

## Откат

Отключить команды ролей. `0003 -> 0002` удаляет только trigger/index, не определения
и назначения; для сохранения защиты опубликованных данных предпочтительно оставить
схему и откатить приложение. Опубликованные версии не переписывать.
