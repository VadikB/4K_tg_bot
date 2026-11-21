# TASK-026: статус готовности текущего кейса

## Источники и граница

Прочитаны `README.md`, `docs/sdd/student-channel-v1.md`,
`docs/architecture/product-4k/telegram-student-channel-v1.md` репозитория 4К,
`app/integrations/agent4k.py`, `app/application/assessments.py`,
`app/bot.py`, `tests/test_student_channel_handlers.py` и сохранённый локальный
черновик. Источник 4К имеет статус `DRAFT`, режим `development_only`;
`docs/evc/decisions/tg-student-channel-risk-acceptance.md` остаётся `pending`.
Прочитанная версия 4К: branch `codex/tg-student-channel-api`,
HEAD `bc63a8ee4a21c36a124dd0040bd44a9f9cccefed`;
blob SHA контракта `6a389f1d957d495545ca6f9a0d68d3fc3aaac701`,
решения `553c2f1b56c86b67bd883bfebfec696ad6be99b1`.
База бота: `main` `c0e0e3cdb2e51a91bd839fac12f86c94fec8b6b8`;
реализация в `codex/case-status`.

В `channel-state` нет поля с количеством подготовленных Case. Число `0` или `1`
означает только доступность **текущего** кейса по каноническому `next_action`
4К. При `technical_failure` число неизвестно. Бот не вычисляет запас Case,
дневной лимит или время ожидания и не изменяет состояние оценки при проверке.

## Результат

- `/case_status [ASSIGNMENT_ID]` показывает состояние каждого доступного
  назначения в личном чате; явный ID сначала проверяется по локальному списку
  назначений пользователя.
- `/get_case` в состоянии подготовки или ожидания направляет к `/case_status`.
- Команда добавлена в Telegram menu, `/start`, `/help` и `README.md`.

## Проверки и выпуск

Локально: `.venv/bin/ruff check .` — PASS; `.venv/bin/mypy app` — PASS
(18 файлов); `.venv/bin/pytest -q -m 'not integration'` — PASS
(103 passed, 24 deselected); `git diff --check` — PASS. Изменений БД, миграции,
зависимостей и контракта 4К нет. Локальный PostgreSQL integration — NOT_RUN:
изолированная БД не запущена. Полный CI на `bot_pytest` ожидается в PR;
реальный 4К и Telegram не вызываются.

Из-за `development_only` и `pending` результат допускается в отдельной ветке
и PR для review. Merge/deploy ожидают отдельного решения владельцев по условиям
`docs/sdd/student-channel-v1.md`; прежний выпуск бота такого решения не заменяет.

## Откат

Удалить обработчик и сообщения команды, вернуть прежнюю подсказку `/get_case`.
Сохранённые назначения, Cycle и данные проектов не затрагиваются.
