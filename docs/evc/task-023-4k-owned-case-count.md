# TASK-023: убрать локальный ввод числа кейсов

## Результат и границы

По решению владельца от 23.11.2026 новый `/new_spec` не спрашивает число кейсов.
Новые настройки проекта сохраняют его неопределённым до плана Cycle 4К. Старые
опубликованные спецификации, назначения и снимки не изменяются.

В область входят мастер, локальный snapshot v2, совместимая expand-миграция,
readback и регрессия. Не входят изменение 4К и пересчёт старых оценок.

## Источники и решение

- Рабочая ветка `codex/4k-owned-case-count`, исходный SHA
  `e9595aa971c34cc0076df02769cb5a955bd518d0` ветки `codex/case-status`.
- Для независимого PR изменение перенесено без `/case_status` на `main`
  `c0e0e3cdb2e51a91bd839fac12f86c94fec8b6b8`: ветка
  `codex/4k-owned-case-count-pr`, SHA
  `0b550019c8f70698b05d12cd687490f147956abd`, Draft PR #11.
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

На точном SHA PR локально 24.11.2026: Ruff — PASS, mypy — PASS,
`pytest -q -m 'not integration'` — PASS (101 passed, 25 deselected),
`git diff --check origin/main...HEAD` — PASS. CI PR #11 — PENDING.
Общий Telegram-контур остаётся отдельным выпускным gate.
Миграция снимает `NOT NULL`, downgrade при новых v2-строках запрещён для сохранения
данных. При отмене изменения использовать совместимый v1/v2 код и остановить
создание новых v2-спецификаций; опубликованные снимки не переписывать.

## План выпуска и открытые условия

После запроса владельца 24.11.2026 ветка отправлена в GitHub и открыт Draft PR
#11 для review/CI. До merge необходимы зелёный CI, решение product owner 4К по
`docs/evc/decisions/tg-student-channel-risk-acceptance.md` и отдельный допуск
выпуска по `docs/sdd/student-channel-v1.md`. Текущий статус — `development_only`;
решение о принятии рисков остаётся `pending`. Запрос «на main и на стенд» сам по
себе не указывает принимающего этот риск и не закрывает условия контракта.

Штатный `deploy/release_remote.sh` сравнивает migration AST и прерывает выпуск
при изменении; новая `0013_optional_case_count` требует ручного пути. Перед
merge release owner должен проверить фактический SHA и `alembic current` стенда,
состояние сервиса и наличие пригодного пути восстановления БД. При допуске:

1. Сохранить предыдущий `app`, `migrations`, `alembic.ini` и точный SHA выпуска.
   Сделать закрытый `pg_dump -Fc` в каталог backup с правами `0600`, проверить
   `pg_restore --list` без вывода содержимого. Восстановление проверить на
   изолированной БД; рабочую БД тестами не использовать.
2. Из точного SHA `main` собрать архив без `.env`, `.venv`, `.git`, секретов и
   пользовательских данных; сверить SHA-256 архива локально и на стенде.
3. Остановить `4k-tg-bot.service`, установить совместимый код и migration files,
   выполнить `alembic upgrade head`, убедиться в `0013_optional_case_count`,
   запустить сервис. Серверные `.env` и `.venv` сохранить.
4. Проверить `ActiveState=active`, `SubState=running`, новый PID, отсутствие
   рестартов/новых ошибок, SHA установленного кода и базовые команды Telegram.
   Зафиксировать результат в карточке: SHA, время и CI, migration до/после,
   состояние сервиса и проверка бота.

При ошибке остановить сервис, вернуть сохранённый код, совместимый с текущей
схемой, и запустить сервис. Схему не сужать до проверки отсутствия v2-строк с
`NULL`; при наличии таких строк оставить `0013` и использовать совместимый код.
Полное восстановление из backup допустимо только по отдельному плану с оценкой
данных, созданных после backup. До фактической проверки статус выпуска `PENDING`.

`branch_push=true`, `pr=true`, `merge=false`, `deploy=false`,
`version_bump=false`, `artifact_publish=false`.
