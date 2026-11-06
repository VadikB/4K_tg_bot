# TASK-010: неизменяемый контекст назначения учебной оценки

## Результат

Для существующего назначения оценки администратор публикует отдельный
`ProjectAssessmentContextSnapshot`. Snapshot получает стабильный `assignment_ref`,
канонический SHA-256 и защищён PostgreSQL trigger от изменения и удаления.

## Область

- Включено: точные ссылки на курс, проект и этапы CRISP-DM, опубликованные версии
  проектной роли и спецификации, `RoleProfileVersion` 4К и технический
  `agent4k_user_id`; команда `/publish_context ASSIGNMENT_ID`.
- Контактные данные исключены: email, Telegram ID, username и display name не входят
  в snapshot.
- Не входит: создание Organization, AssessmentProgram или Assessment Cycle в 4К;
  внешний API публикации контекста остаётся следующей задачей.

## Источники и решения

- Архитектурное решение TGBOT-02/TGBOT-03 в 4К: курс и поток соответствуют
  Organization, а проект и роль фиксируются в контексте конкретного назначения.
- Локальные источники: `README.md`, TASK-008, TASK-009, существующие модели
  `AssessmentAssignment`, `ProjectAssessmentSpec` и `ProjectRoleVersion`.
- Один snapshot соответствует ровно одному назначению. Повторная команда идемпотентна
  и возвращает уже опубликованный snapshot после проверки checksum.
- `assignment_ref` не содержит персональных данных и имеет формат
  `edu:4k-tg-bot:p{project_id}:a{assignment_id}`.

## Проверки

- Ruff → PASS; mypy → PASS.
- Unit → 34 PASS.
- PostgreSQL integration → 12 PASS.
- Alembic `0007 -> 0006 -> head` → PASS.
- `git diff --check` → PASS.
- Реальное создание Cycle 4К → NOT_RUN: endpoint ещё не реализован и не входит в задачу.

## Действия выпуска

`branch_push=false`, `pr=false`, `merge=false`, `deploy=false`,
`version_bump=false`, `artifact_publish=false`.

## Откат

До появления опубликованных snapshot выполнить downgrade `0007 -> 0006`. После
публикации данные не переписывать: для изменения контекста создать новое назначение.
