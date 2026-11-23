# TASK-023: убрать локальный ввод числа кейсов

## Результат и границы

По решению владельца от 23.11.2026 новый `/new_spec` не спрашивает число кейсов.
Новые настройки проекта сохраняют его неопределённым до плана Cycle 4К. Старые
опубликованные спецификации, назначения и снимки не изменяются.

В область входят мастер, локальный snapshot v2, совместимая expand-миграция,
readback и регрессия. Не входят изменение 4К, пересчёт старых оценок, выпуск,
merge и deploy.

## Источники и решение

- Рабочая ветка `codex/4k-owned-case-count`, исходный SHA
  `e9595aa971c34cc0076df02769cb5a955bd518d0` ветки `codex/case-status`.
- `README.md`, `docs/sdd/student-channel-v1.md`, `docs/sdd/project-assessment-spec-v2.md`.
- Историческое решение `docs/evc/task-020-assessment-configuration-selection.md`
  сохранять число локально заменено новым прямым решением владельца только для
  новых настроек.
- 4К: `docs/architecture/product-4k/telegram-student-channel-v1.md` §Совместимость;
  `Api/educational_contexts.py` возвращает progress по маршруту Cycle.
- Неподтверждённый вход: список AssessmentConfiguration не содержит числа кейсов.
  Поле не заполняется догадкой или встроенным default.

## Проверки и откат

Локально 23.11.2026:

- `.venv/bin/pytest -q -m 'not integration'` → PASS, 104 passed;
  25 integration deselected.
- `.venv/bin/ruff check .` → PASS.
- `.venv/bin/mypy app` → PASS, 18 modules.
- `.venv/bin/python -m compileall -q app migrations/versions/0013_optional_case_count.py`
  → PASS.
- `git diff --check` → PASS.
- Первый PostgreSQL-прогон выявил конфликт двух Alembic heads: новая миграция
  ошибочно заняла `0012`. Исправлена на `0013_optional_case_count` после
  существующей `0012_opaque_subject`.
- `TEST_DATABASE_URL=…/case_count_pytest .venv/bin/pytest -q -m integration`
  → PASS, 25 passed на временной PostgreSQL 16 в отдельном Docker container;
  новый v2 и исторический v1 readback прошли.
- Общий Telegram/4К и CI → NOT_RUN до candidate/PR и выпуска.

Общий Telegram-контур и CI остаются отдельным выпускным gate.
Миграция снимает `NOT NULL`, downgrade при новых v2-строках запрещён для сохранения
данных. При отмене изменения использовать совместимый v1/v2 код и остановить
создание новых v2-спецификаций; опубликованные снимки не переписывать.

`branch_push=false`, `pr=false`, `merge=false`, `deploy=false`,
`version_bump=false`, `artifact_publish=false`.
