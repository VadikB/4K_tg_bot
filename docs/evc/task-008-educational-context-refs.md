# TASK-008: ссылки учебного контекста на курс и роль 4К

## Результат

Новый проект содержит стабильный `course_external_id`, а новая версия роли CRISP-DM —
обязательную точную ссылку на опубликованную `RoleProfileVersion` 4К (`id + checksum`).

## Область

- Включено: данные, Telegram-мастера, checksum роли, PostgreSQL constraints,
  immutable guard, совместимая миграция и тесты.
- Не входит: проверка ссылки через API 4К, общий project assignment snapshot,
  Organization/PersonalizedProfile/AssessmentProgram и Cycle.

## Источники и решения

- Решение владельца от 06.11.2026: курс — Organization; проект и роли — frozen
  assignment context; явное сопоставление с published M3 RoleProfileVersion обязательно.
- Base: `be0dab5`.
- Архитектурный контракт 4К: commit `fcccb4ce`, задача TGBOT-02.
- Legacy-проекты и опубликованные роли мигрируют с `NULL`; они остаются читаемыми,
  но не допускаются к новому Cycle до выпуска новой сопоставленной версии.
- Ссылка на роль входит в `definition_json` и его checksum, хранится также отдельными
  колонками для admission-проверки и защищена immutable trigger после публикации.

## Критерии приёмки

- [x] Новый проект без корректного стабильного ID курса не создаётся.
- [x] Новая роль без положительного ID и SHA-256 роли 4К не создаётся.
- [x] Mapping входит в checksum опубликованной роли.
- [x] Mapping опубликованной роли нельзя изменить в PostgreSQL.
- [x] Legacy-строки сохраняются без выдуманных ссылок.

## Проверки

- Ruff → PASS.
- mypy → PASS, 16 source files.
- Unit → PASS, 33 tests.
- PostgreSQL integration → PASS, 11 tests.
- Alembic `0006 -> 0005 -> 0006` → PASS.
- `git diff --check` → PASS.
- Реальная HTTP-валидация ID/checksum через API 4К → PASS контрактными тестами:
  опубликованная ссылка принимается, mismatch/недоступность не публикуют draft.

## Действия выпуска

`branch_push=false`, `pr=false`, `merge=false`, `deploy=false`,
`version_bump=false`, `artifact_publish=false`.

## Откат

Вернуть мастера и приложение, затем downgrade `0006 -> 0005`. Новые mapping-поля
будут удалены; опубликованные snapshot не переписывать. Перед downgrade выгрузить
новые ссылки для восстановления.

## Следующий шаг

Read-only service API 4К и проверка перед публикацией выполнены. Следующий шаг —
публиковать единый `ProjectAssessmentContextSnapshot` назначения.
