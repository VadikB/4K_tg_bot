# TASK-015: draft-клиент Telegram Student Channel

## Результат

В изолированной ветке реализовать выключенный клиент Channel API и Telegram-путь
до первого Case/AS против fake/mock контракта.

## Область

- Включено: adapter, технический operation state, `/case`, выбор назначения,
  `/progress` из API, retry/stale handling и tests.
- Не входит: реальное подключение 4К, merge, deploy, Results, multi-organization,
  локальная предметная логика Case/progress.

## Основание и состояние

- SDD: `docs/sdd/student-channel-v1.md`, `DRAFT`.
- Ветка: `codex/tg-student-channel-client`.
- Base SHA: `ae42436cabd015a28badbde09dbef796cb82bf28`.
- Product owner разрешил разработку в отдельных ветках 10.11.2026.
- Риски интеграции ещё не приняты.
- Прочитано для текущего шага: `docs/sdd/student-channel-v1.md` (§4–10,
  `DRAFT`), Agent4K `docs/architecture/product-4k/telegram-student-channel-v1.md`
  (ошибки `409/422`, retry и локальные данные), `Api/integration_routes.py`
  (фактические HTTP-коды), `docs/evc/agent-workflow.md`, `verification-matrix.md`,
  `artifact-recipe.md`, Change 01 и task manifest. Методологические M1/M5
  источники не менялись и не используются для введения новых норм.
- Пробел: общий контур и полный Telegram→HTTP→4К путь не испытаны; работа остаётся
  в изолированном draft. Нового решения о предметном содержании не требуется.

## План

1. [x] Добавить typed adapter channel state/actions и fake implementation.
2. [x] Спроектировать только техническое хранение операций с совместимым rollback.
3. [x] Реализовать выбор assignment при нескольких проектах/ролях.
4. [x] Заменить `/case` для включённого draft-mode, сохранив fail-closed default.
5. [x] Перевести draft `/progress` на API projection.
6. [x] Покрыть unit/handler/integration тестами без реального 4К.

## Стоп-условия

- Нельзя подключать общий контур или хранить integration token в Git.
- Нельзя встраивать Case, Questionnaire, Profile, лимиты или расчёт progress.
- Нельзя писать ответы студента в application logs.
- Нельзя включать новый путь по умолчанию.

## Критерии приёмки draft-кандидата

- [x] Default остаётся fail-closed.
- [x] Несколько проектов/ролей изолированы по assignment scope.
- [x] Retry использует тот же idempotency key.
- [x] Stale Telegram action не повторяет ответ.
- [x] Fake contract покрывает Questionnaire/Profile/первый Case/progress.
- [x] Реальная интеграция и deployment имеют статус NOT_RUN.

## Текущий независимый slice

Добавлены typed `channel-state` и `channel-actions` в `Agent4KPort`, disabled adapter
и HTTP adapter. `/my_projects`, фильтр `/my_roles PROJECT`, `/case [ASSIGNMENT_ID]`
и `/progress [ASSIGNMENT_ID]` используют только опубликованные context snapshot,
принадлежащие текущему Telegram user. Локальный ID преобразуется в сохранённый
`assignment_ref` внутри application service; значение пользователя не считается
доверенным scope. `/case` автоматически исполняет только `input.kind=confirm` с
детерминированным idempotency key и отображает только participant payload.

Свободный текст `Questionnaire`/`case_turn` передаётся через технический binding
Telegram message к `action_id + revision`. Таблица
`student_channel_input_bindings` не содержит текста ответа: только scope, revision,
idempotency key, checksum input, Telegram routing IDs и статус. Timeout оставляет
binding pending; повтор принимает только тот же текст и использует тот же ключ.
  `sending` сериализует одновременные сообщения, lease позволяет восстановиться
после аварийного завершения процесса. `409 stale` переводит запись в `stale`,
`/cancel` закрывает pending binding. Следующий текстовый action из committed ответа
привязывается сразу. Case и progress доступны только в личном чате, длинная
  проекция разбивается на сообщения Telegram. Ответ передаётся без изменения
  пробелов; следующий `confirm` предлагает точную команду `/case ASSIGNMENT_ID`.

Проверки:

- `ruff check .` → PASS; `mypy app tests/synthetic_semester.py` → PASS,
  17 source files.
- Telegram handler и HTTP adapter, включая `409`/private chat/длинный Case и
  fake-путь consent → три ответа → Profile → первый Case Turn → progress →
  PASS, `16 passed` адресно; provider trace не отображается.
- Весь `tests/integration/test_project_service.py` на изолированной PostgreSQL →
  PASS, `13 passed`: scope, text submit, checksum, конфликт другого текста,
  повтор после timeout, восстановление истёкшего `sending` lease,
  конкурентная отправка и stale. Disposable
  `tg_bot_synthetic_pytest` удалена после прогона.
- Общий локальный набор `.venv/bin/pytest -q` → PASS, `58 passed, 13 skipped`;
  skipped — integration без `TEST_DATABASE_URL`, отдельно выполнены выше.
- `git diff --check` → PASS.
- Migration `upgrade head → downgrade 0008 → upgrade head` → PASS на disposable
  `tg_bot_migration_pytest`; база удалена после прогона.
- Синтетический cross-repository прогон `/case` → текстовый Turn → `/progress`
  через HTTP/ASGI и две disposable PostgreSQL-БД выполнен в 4К
  `tests/integration/test_telegram_student_channel_cross_repo.py` → PASS,
  `1 passed`: потеря ответа и replay не создают второй Turn, binding хранит
  checksum без текста. Это не реальный Telegram API, не общий deployment и не
  полный путь Questionnaire → Profile → Case. CI и deploy → NOT_RUN;
  draft-клиент не готов к включению общего контура.

## Текущий статус и передача

Дополнение 10.11.2026: `/progress` показывает точное `next_available_at` из 4К,
если оно есть, без локального вычисления дневного лимита. Режим `mock` при запуске
требует HTTP-стаб на loopback и выбирает HTTP adapter, а не disabled adapter;
production и внешний адрес в режиме `mock` запрещены. Локальный набор после
этих и смежных изменений — 85 PASS на изолированной PostgreSQL test-БД.

- Branch `codex/tg-student-channel-client`; base
  `ae42436cabd015a28badbde09dbef796cb82bf28`. Клиент и синтетический harness
  выделены из смешанного checkpoint в независимого кандидата; локальный полный
  `pytest` на изолированной PostgreSQL test-БД — PASS, 73 теста. Кандидатный SHA
  фиксируется после коммита; CI и реальный Telegram — NOT_RUN.
- Изменения: `app/application/assessments.py`, `app/bot.py`,
  `app/integrations/agent4k.py`, `app/models.py`, migration `0009`,
  `tests/test_agent4k_adapter.py`, `tests/test_student_channel_handlers.py`,
  `tests/integration/test_project_service.py`, `README.md`, эта карточка.
- Следующий шаг: единый изолированный Questionnaire → Profile → Case прогон,
  совместимые candidate SHA и решение владельцев по рискам интеграции;
  методологический допуск и выпуск остаются отдельными решениями.

## Действия выпуска

`branch_push=false`, `pr=false`, `merge=false`, `deploy=false`,
`version_bump=false`, `artifact_publish=false`.

## Откат

Выключить draft feature. До production-записей допустим downgrade `0009`; после
записей сохранить operation metadata и не удалять историю 4К. Данные основного 4К
не затрагиваются.
