# TASK-016: Synthetic Semester Harness

## Результат

Создать воспроизводимый механизм проверки Telegram Student Channel без реальных
студентов: синтетические проекты и участники, frozen роли из исходного документа,
машинный PASS/FAIL и явные границы доказательства.

## Источники и решения

- Владелец продукта 10.11.2026 согласовал механизм и неизменность ролей на текущей стадии.
- Источник ролей: `ТГ бот для студентов.md`, разделы о ролях и взаимодействиях CRISP-DM.
- Профиль прогона: Agent4K `docs/evc/assessment-first-case-profile.md`, версия
  `assessment-first-case/1.1`.
- Процесс артефакта: Agent4K `docs/evc/artifact-recipe.md`.
- Пакет размещён в `tests/fixtures`, потому что это QA-only fixture, а не предметный
  runtime-пакет `assessment_definitions`.

## Границы

- Входит: технический путь, scope-изоляция, retry, отсутствие контактной identity,
  первая AS и канонический progress.
- Не входит: методологическая валидность, качество LLM, UX-приёмка реальными
  студентами, публикация роли/методологии, production/test deployment.
- Синтетический PASS не является PASS продукта до фактического DB/API readback.

## Артефакты

- `tests/fixtures/synthetic_semester/v1/manifest.json` — версия, статус и checksum.
- `roles.json` — пять frozen ролей.
- `scenarios.json` — два сценария первого эшелона.
- `tests/synthetic_semester.py` — загрузчик и topology-evaluator.
- `tests/test_synthetic_semester.py` — позитивные и негативная регрессии.

## План

1. [x] Зафиксировать QA-only contract и роли вне исходного кода.
2. [x] Добавить `single-role-first-case` и `multi-project-multi-role-isolation`.
3. [x] Проверить checksum, ссылки ролей и обнаружение cross-assignment Profile.
4. [x] Добавить disposable seed/readback Telegram PostgreSQL.
5. [x] Завершить Channel API readback всех трёх назначений: context registration,
   operation replay, acquaintance и три разных RoleProfile/Profile/Cycle/progress
   проходят составной технический контур.
6. [x] Достичь первой AS через deterministic gateway.
7. [x] Сформировать JSON evidence; candidate SHA остаётся `null` до коммита.

## Проверки

- `.venv/bin/pytest -q tests/test_synthetic_semester.py` — PASS, 5 tests.
- `.venv/bin/ruff check .` — PASS.
- `.venv/bin/mypy app tests/synthetic_semester.py` — PASS, 17 source files.
- `.venv/bin/pytest -q` — PASS, `51 passed, 13 skipped` (integration без DB URL).
- `git diff --check` — PASS.
- `TEST_DATABASE_URL=postgresql+asyncpg://…/tg_bot_synthetic_pytest .venv/bin/pytest
  -m integration tests/integration/test_project_service.py::test_synthetic_semester_multi_project_role_assignment_readback -q`
  — PASS, `1 passed`; отдельная БД создана перед прогоном и удалена после него.
- Фактический readback: один Telegram user, два ProjectParticipant в разных проектах,
  три опубликованных role assignments, три AssessmentAssignment и три уникальных
  context `assignment_ref`; topology-evaluator — PASS.
- PostgreSQL бота — PASS.
- PostgreSQL 4К multi-context Assignment/snapshot — PASS, `6 passed`; Profile/Cycle/
  progress для всех трёх назначений вместе — PASS.
- Channel API до первой AS + exact replay/conflict — PASS, `1 passed`.
- Scoped acquaintance трёх Assignment — PASS, `2 passed`.
- Три разных published base RoleProfile → три exact PersonalizedProfile → три Cycle
  → три channel progress — PASS, `1 passed`.
- Ограничение: M10 fixture использует `SYNTHETIC_UPSTREAM_START_PERMISSION_NOT_HUMAN_ADMISSION`;
  технический PATH не является методологическим admission или результатом оценки.
- Ограничение: Telegram assignments и Agent4K Profile/Cycle проверены составными
  тестами двух репозиториев, а не одной cross-repository транзакцией/API-сессией.
- Дополнение 10.11.2026: отдельный cross-repository тест в 4К прошёл
  `/case` → первый текстовый Turn → `/progress` через HTTP/ASGI и две disposable
  БД, включая retry после потери ответа. Он закрывает этот технический участок,
  но не превращает составные Questionnaire → Profile → Case проверки в единый
  сквозной прогон и не включает реальный Telegram API или LLM.
- Ограничение: соответствие учебных CRISP-DM-ролей конкретным 4К RoleProfile в
  synthetic fixture не является методологическим утверждением.

## Откат

Удалить QA-пакет, evaluator, тест и эту карточку. Runtime-данные и схемы текущим
шагом не изменяются; миграция и восстановление не требуются.

## Действия выпуска

`branch_push=false`, `pr=false`, `merge=false`, `deploy=false`,
`artifact_publish=false`, `real_students=false`, `real_llm=false`.
